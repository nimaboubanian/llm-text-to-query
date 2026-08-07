"""Stage: LLM SQL generation and generated-query execution, per seed."""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from backend.core.config import LLM_MAX_TOKENS, LLM_TEMPERATURE, PROMPT_FLAGS
from backend.database.executor import explain_error
from backend.database.schema import create_engine_for_database, load_tpch_metadata, render_schema
from backend.llm import ollama
from backend.llm.prompt_builder import build_prompt
from backend.benchmark.data_loader import TPCH_TABLES
from backend.benchmark.fingerprint import (
    MANIFEST_FILENAME, GenerationFingerprint, read_manifest_fingerprint, write_manifest,
)
from backend.benchmark.pipeline import execute_queries_to_csv, read_business_question
from backend.benchmark.progress import print_item_done, print_item_start


def run_llm_generation(
    questions_dir: Path,
    output_dir: Path,
    db_url: str,
    model: str,
    seeds: list[int] | None = None,
    query_ids: list[str] | None = None,
) -> None:
    seeds = seeds or [1]
    for seed in seeds:
        seed_dir = output_dir / f"seed_{seed}"
        if len(seeds) > 1:
            print(f"  --- Seed {seed} ---")
        _run_single_generation(
            questions_dir, seed_dir, db_url, model, seed=seed, query_ids=query_ids,
        )


def _run_single_generation(
    questions_dir: Path,
    output_dir: Path,
    db_url: str,
    model: str,
    seed: int | None = None,
    query_ids: list[str] | None = None,
    on_item_start=print_item_start,
    on_item_done=print_item_done,
) -> None:
    # Digest is over the FULL question set, independent of query_ids filtering below —
    # otherwise a --query-ids re-run (e.g. resuming just the failed queries after an
    # interrupted run) would change the fingerprint and wipe the entire generation cache.
    all_questions = sorted(questions_dir.glob("*.md"))
    questions_digest = hashlib.sha256(
        "\n".join(f.read_text() for f in all_questions).encode()
    ).hexdigest()[:16]

    question_files = [q for q in all_questions if query_ids is None or q.stem in query_ids]

    output_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine_for_database(db_url)
    schema = render_schema(engine, PROMPT_FLAGS, metadata=load_tpch_metadata(),
                           include_tables=set(TPCH_TABLES))

    fingerprint = GenerationFingerprint(
        model=model,
        prompt_template=build_prompt(PROMPT_FLAGS, "{schema}", "{query}"),
        schema=schema,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        seed=seed,
        retry_on_error=PROMPT_FLAGS.retry_on_error,
        questions=questions_digest,
    )

    cached_fingerprint = read_manifest_fingerprint(output_dir)
    if cached_fingerprint is not None and cached_fingerprint != fingerprint.hash:
        print(f"  ⚠ Generation config changed since last run — clearing stale cache in {output_dir}")
        _clear(output_dir, ("*.sql", "*.prompt", "*.raw", "*.timing.json"))
    write_manifest(output_dir, fingerprint.hash, asdict(fingerprint))

    # Cache: skip queries whose .sql file already exists. Safe to resume from — the
    # fingerprint check above guarantees the cache reflects the current model, prompt,
    # schema, temperature, and seed; a mismatch clears it before we get here.
    existing = {f.stem for f in output_dir.glob("*.sql")}
    to_process = [q for q in question_files if q.stem not in existing]

    if not to_process:
        print(f"  ✓ All {len(question_files)} queries already generated")
        return

    seed_label = f" (seed={seed})" if seed is not None else ""
    cache_label = f", {len(existing)} cached" if existing else ""
    print(f"  Generating {len(to_process)} queries{seed_label}{cache_label}...")

    print(f"  Warming up {model}...", end="", flush=True)
    print(" ✓" if ollama.warmup(model) else " ⚠ (warmup failed, continuing)")

    success = 0
    retries = 0
    errors = []

    for i, qfile in enumerate(to_process, 1):
        query_id = qfile.stem
        on_item_start(i, len(to_process), f"Q{query_id}")

        question = read_business_question(qfile)
        if not question:
            on_item_done(" ⚠ no question found, skipping")
            continue

        result = ollama.generate_sql_with_retry(
            question, schema, model, seed=seed,
            validate=lambda sql: explain_error(engine, sql),
        )
        retries += result.retried

        if result.retried and result.first_prompt is not None:
            (output_dir / f"{query_id}.prompt").write_text(result.first_prompt)
            (output_dir / f"{query_id}.retry.prompt").write_text(result.prompt)
        elif result.prompt is not None:
            (output_dir / f"{query_id}.prompt").write_text(result.prompt)

        if result.duration_seconds is not None:
            (output_dir / f"{query_id}.timing.json").write_text(json.dumps({
                "prompt_eval_count": result.prompt_eval_count,
                "eval_count": result.eval_count,
                "duration_seconds": result.duration_seconds,
            }))

        if result.sql:
            (output_dir / f"{query_id}.sql").write_text(result.sql)
            on_item_done(" ✓")
            success += 1
        else:
            if result.error is not None or result.raw_response is not None:
                (output_dir / f"{query_id}.raw").write_text(
                    f"ERROR: {result.error}\n" if result.error else result.raw_response
                )
            on_item_done(" ✗")
            errors.append((query_id, result.error or "No SQL extracted"))

    print(f"  ✓ Generated {success} queries")
    if retries:
        print(f"  ↻ {retries} queries needed a retry")
    if errors:
        print(f"  ⚠ {len(errors)} failed:")
        for query_id, error in errors:
            print(f"    - Q{query_id}: {error[:60]}")


def execute_generated_queries(
    queries_dir: Path,
    answers_dir: Path,
    db_url: str,
    seeds: list[int] | None = None,
    query_ids: list[str] | None = None,
) -> None:
    seeds = seeds or [1]
    for seed in seeds:
        seed_queries = queries_dir / f"seed_{seed}"
        seed_answers = answers_dir / f"seed_{seed}"
        if len(seeds) > 1:
            print(f"  --- Seed {seed} ---")
        _execute_single(seed_queries, seed_answers, db_url, query_ids=query_ids)


def _execute_single(
    queries_dir: Path,
    answers_dir: Path,
    db_url: str,
    query_ids: list[str] | None = None,
) -> None:
    query_files = [
        q for q in sorted(queries_dir.glob("*.sql")) if query_ids is None or q.stem in query_ids
    ]

    answers_dir.mkdir(parents=True, exist_ok=True)

    # The generated queries carry a fingerprint from run_llm_generation. If it no longer
    # matches what these answers were last executed against, the queries were regenerated
    # since — clear the stale answers so they can't be paired with the new queries.
    generation_fingerprint = read_manifest_fingerprint(queries_dir)
    cached_fingerprint = read_manifest_fingerprint(answers_dir)
    if (
        generation_fingerprint is not None
        and cached_fingerprint is not None
        and cached_fingerprint != generation_fingerprint
    ):
        print(f"  ⚠ Generated queries changed since last execution — clearing stale answers in {answers_dir}")
        _clear(answers_dir, ("*.csv", "*.error"))
    if generation_fingerprint is not None:
        write_manifest(answers_dir, generation_fingerprint, {"source": str(queries_dir / MANIFEST_FILENAME)})

    existing = {f.stem for f in answers_dir.glob("*.csv")} | {f.stem for f in answers_dir.glob("*.error")}
    to_process = [q for q in query_files if q.stem not in existing]

    if not to_process:
        print(f"  ✓ All {len(query_files)} answer files already exist")
        return

    cache_label = f", {len(existing)} cached" if existing else ""
    print(f"  Executing {len(to_process)} queries{cache_label}...")
    execute_queries_to_csv(to_process, answers_dir, db_url, write_error_file=True)


def _clear(directory: Path, patterns: tuple[str, ...]) -> None:
    for pattern in patterns:
        for f in directory.glob(pattern):
            f.unlink()
