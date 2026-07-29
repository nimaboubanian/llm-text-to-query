"""Stage: LLM SQL generation and generated-query execution, per seed."""
from dataclasses import asdict
from pathlib import Path

from text2query.core.config import LLM_MAX_TOKENS, LLM_TEMPERATURE, PROMPT_FLAGS
from text2query.database.schema import create_engine_for_database, render_schema
from text2query.llm import ollama
from text2query.llm.prompt_builder import build_prompt
from text2query.benchmark.fingerprint import (
    MANIFEST_FILENAME, GenerationFingerprint, read_manifest_fingerprint, write_manifest,
)
from text2query.benchmark.pipeline import execute_queries_to_csv, read_business_question
from text2query.benchmark.progress import print_item_done, print_item_start


def run_llm_generation(
    questions_dir: Path,
    output_dir: Path,
    db_url: str,
    model: str,
    seeds: list[int] | None = None,
    query_ids: list[str] | None = None,
) -> None:
    for seed in seeds or [1]:
        seed_dir = output_dir / f"seed_{seed}"
        print(f"\n  --- Seed {seed} ---")
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
    question_files = sorted(questions_dir.glob("*.md"))
    if query_ids is not None:
        question_files = [q for q in question_files if q.stem in query_ids]
    total = len(question_files)

    output_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine_for_database(db_url)
    schema = render_schema(engine, PROMPT_FLAGS)

    fingerprint = GenerationFingerprint(
        model=model,
        prompt_template=build_prompt(PROMPT_FLAGS, "{schema}", "{query}"),
        schema=schema,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        seed=seed,
    )

    cached_fingerprint = read_manifest_fingerprint(output_dir)
    if cached_fingerprint is not None and cached_fingerprint != fingerprint.hash:
        print(f"  ⚠ Generation config changed since last run — clearing stale cache in {output_dir}")
        _clear(output_dir, ("*.sql", "*.prompt", "*.raw"))
    write_manifest(output_dir, fingerprint.hash, asdict(fingerprint))

    # Cache: skip queries whose .sql file already exists. Safe to resume from — the
    # fingerprint check above guarantees the cache reflects the current model, prompt,
    # schema, temperature, and seed; a mismatch clears it before we get here.
    existing = {f.stem for f in output_dir.glob("*.sql")}
    to_process = [q for q in question_files if q.stem not in existing]

    if not to_process:
        print(f"  ✓ All {total} queries already generated in {output_dir}")
        return

    seed_label = f" (seed={seed})" if seed is not None else ""
    cache_label = f", {len(existing)} cached" if existing else ""
    print(f"  Generating {len(to_process)} queries{seed_label}{cache_label}...")

    print(f"  Warming up {model}...", end="", flush=True)
    print(" ✓" if ollama.warmup(model) else " ⚠ (warmup failed, continuing)")

    success = 0
    errors = []
    process_total = len(to_process)

    for i, qfile in enumerate(to_process, 1):
        query_id = qfile.stem
        question = read_business_question(qfile)
        if not question:
            on_item_start(i, process_total, f"Q{query_id}")
            on_item_done(" ⚠ no question found, skipping")
            continue

        on_item_start(i, process_total, f"Q{query_id}")

        result = ollama.generate_sql(question, schema, model, seed=seed)
        generated_sql = result.sql
        raw_response = result.raw_response
        prompt = result.prompt
        error = result.error

        if prompt is not None:
            (output_dir / f"{query_id}.prompt").write_text(prompt)

        if generated_sql:
            output_file = output_dir / f"{query_id}.sql"
            output_file.write_text(generated_sql)
            on_item_done(" ✓")
            success += 1
        else:
            raw_file = output_dir / f"{query_id}.raw"
            if error:
                raw_file.write_text(f"ERROR: {error}\n")
            elif raw_response:
                raw_file.write_text(raw_response)
            on_item_done(" ✗")
            errors.append((query_id, error or "No SQL extracted"))

    print(f"  ✓ Generated {success} queries -> {output_dir}")
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
    for seed in seeds or [1]:
        seed_queries = queries_dir / f"seed_{seed}"
        seed_answers = answers_dir / f"seed_{seed}"
        print(f"\n  --- Seed {seed} ---")
        _execute_single(seed_queries, seed_answers, db_url, query_ids=query_ids)


def _execute_single(
    queries_dir: Path,
    answers_dir: Path,
    db_url: str,
    query_ids: list[str] | None = None,
) -> None:
    query_files = sorted(queries_dir.glob("*.sql"))
    if query_ids is not None:
        query_files = [q for q in query_files if q.stem in query_ids]
    total = len(query_files)

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
        print(f"  ✓ All {total} answer files already exist in {answers_dir}")
        return

    cache_label = f", {len(existing)} cached" if existing else ""
    print(f"  Executing {len(to_process)} queries{cache_label}...")
    execute_queries_to_csv(to_process, answers_dir, db_url, write_error_file=True)


def _clear(directory: Path, patterns: tuple[str, ...]) -> None:
    for pattern in patterns:
        for f in directory.glob(pattern):
            f.unlink()
