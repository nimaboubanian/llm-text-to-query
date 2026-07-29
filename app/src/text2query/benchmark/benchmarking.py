#!/usr/bin/env python3
"""Benchmark CLI entry point: orchestrates the full evaluation pipeline end to end."""

from dataclasses import asdict, dataclass
import logging
import time
from pathlib import Path
import sys

from text2query.benchmark.pipeline import (
    generate_data,
    validate_directories,
    check_database_readiness,
    setup_database,
    generate_answers,
)
from text2query.benchmark.runner import (
    run_llm_generation,
    execute_generated_queries,
)
from text2query.benchmark.reporting import (
    generate_reports,
    generate_cross_model_report,
    archive_session,
    write_session_manifest,
    format_run_summary,
    format_session_header,
)
from text2query.benchmark.fingerprint import collect_fingerprints


def _banner(title: str) -> str:
    """Render a light section divider padded to 60 columns, matching the header/footer width."""
    prefix = f"─── {title} "
    return prefix + "─" * max(3, 60 - len(prefix))


@dataclass(frozen=True)
class BenchmarkPaths:
    """Filesystem layout for a benchmark run."""
    schema_file: Path = Path("benchmark/.tpch/schema.sql")
    questions_dir: Path = Path("benchmark/.tpch/questions")
    queries_dir: Path = Path("benchmark/.tpch/queries")
    answers_dir: Path = Path("benchmark/.tpch/answers")
    output_dir: Path = Path("benchmark/queries")
    generated_answers_dir: Path = Path("benchmark/answers")
    report_dir: Path = Path("benchmark/reports")
    results_base: Path = Path("benchmark/results")


def _run_single_model_benchmark(
    model: str,
    paths: BenchmarkPaths,
    db_url: str,
    seeds: list[int] | None,
    query_ids: list[str] | None = None,
) -> list[dict]:
    """Run the full benchmark (generate + execute + report) for one model."""
    slug = model.replace(":", "_").replace("/", "_")
    output_dir = paths.output_dir / slug
    generated_answers_dir = paths.generated_answers_dir / slug
    report_dir = paths.report_dir / slug

    print(_banner("SQL Generation"))
    run_llm_generation(
        questions_dir=paths.questions_dir, output_dir=output_dir,
        db_url=db_url, model=model,
        seeds=seeds, query_ids=query_ids,
    )
    print()

    print(_banner("Execution"))
    execute_generated_queries(
        queries_dir=output_dir, answers_dir=generated_answers_dir, db_url=db_url,
        seeds=seeds, query_ids=query_ids,
    )
    print()

    print(_banner("Evaluation"))
    results = generate_reports(
        generated_queries_dir=output_dir, reference_queries_dir=paths.queries_dir,
        generated_answers_dir=generated_answers_dir, reference_answers_dir=paths.answers_dir,
        report_dir=report_dir,
        seeds=seeds,
        model=model,
        selected_ids=query_ids,
        questions_dir=paths.questions_dir,
    )
    print()

    return results


def _resolve_query_id_filter(
    requested: list[str] | None, available: list[str],
) -> tuple[list[str] | None, list[str]]:
    """Validate a BENCHMARK_QUERY_IDS-style filter against available query IDs.

    Returns (resolved_ids, skipped_ids). resolved_ids is None when no filter
    is requested, or an empty list when a filter is requested but nothing in
    it matches `available`.
    """
    if requested is None:
        return None, []
    valid = [q for q in requested if q in available]
    skipped = [q for q in requested if q not in available]
    return valid, skipped


def main():
    from text2query.core.config import (
        DATABASE_URL,
        DEFAULT_MODEL,
        BENCHMARK_SCALE_FACTOR,
        BENCHMARK_DATA_PATH,
        BENCHMARK_NUM_SEEDS,
        BENCHMARK_MODELS,
        BENCHMARK_QUERY_IDS,
        LLM_TEMPERATURE,
        LLM_MAX_TOKENS,
        LLM_NUM_CTX,
        LOG_LEVEL,
        PROMPT_FLAGS,
    )

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.WARNING),
        format="%(levelname)s %(name)s: %(message)s",
    )

    paths = BenchmarkPaths()
    data_dir = Path(BENCHMARK_DATA_PATH) if BENCHMARK_DATA_PATH else Path(f"benchmark/.tpch/data/sf{BENCHMARK_SCALE_FACTOR}")

    seeds = list(range(1, BENCHMARK_NUM_SEEDS + 1))
    if BENCHMARK_MODELS:
        models = BENCHMARK_MODELS
        fallback_warning = None
    else:
        models = [DEFAULT_MODEL]
        fallback_warning = f"BENCHMARK_MODELS is empty — falling back to DEFAULT_MODEL ({DEFAULT_MODEL})."
    multi_model = len(models) > 1

    start_time = time.monotonic()

    try:
        # Resolve the query filter, then announce the whole session up front.
        available = sorted(f.stem for f in paths.queries_dir.glob("*.sql"))
        query_ids, skipped = _resolve_query_id_filter(BENCHMARK_QUERY_IDS, available)

        print(format_session_header(
            scale_factor=BENCHMARK_SCALE_FACTOR,
            models=models,
            total_available=len(available),
            query_ids=query_ids,
            num_seeds=BENCHMARK_NUM_SEEDS,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            num_ctx=LLM_NUM_CTX,
            prompt_flags=asdict(PROMPT_FLAGS),
            database_url=DATABASE_URL,
        ))

        if fallback_warning:
            print(f"  ⚠ {fallback_warning}")
        if skipped:
            print(f"  ⚠ Unknown query IDs (skipped): {', '.join(skipped)}")
        if query_ids is not None and not query_ids:
            print("  ✗ No valid query IDs remain after filtering — aborting")
            sys.exit(1)
        if fallback_warning or skipped:
            print()

        # === Phase 1: Setup (shared across all models) ===
        print(_banner("Setup"))
        if BENCHMARK_DATA_PATH:
            print(f"  Using existing data: {BENCHMARK_DATA_PATH}")
            data_dir = Path(BENCHMARK_DATA_PATH)
        else:
            data_dir = generate_data(BENCHMARK_SCALE_FACTOR, data_dir)

        validate_directories(paths.questions_dir, paths.queries_dir)

        is_ready = check_database_readiness(db_url=DATABASE_URL)
        if not is_ready:
            setup_database(
                schema_file=paths.schema_file,
                data_dir=data_dir,
                db_url=DATABASE_URL,
            )

        generate_answers(queries_dir=paths.queries_dir, answers_dir=paths.answers_dir, db_url=DATABASE_URL)
        print()

        # === Phase 2+3: Per-model benchmark ===
        precomputed = {}
        for i, model in enumerate(models, 1):
            if multi_model:
                print("═" * 60)
                print(f"  Model {i}/{len(models)}: {model}")
                print("═" * 60)
                print()

            results = _run_single_model_benchmark(
                model=model,
                paths=paths,
                db_url=DATABASE_URL,
                seeds=seeds,
                query_ids=query_ids,
            )
            precomputed[model] = results

        # === Cross-model comparison (if multi-model) ===
        if multi_model:
            print(_banner("Cross-Model Comparison"))
            generate_cross_model_report(
                models=models,
                reference_queries_dir=paths.queries_dir,
                report_dir=paths.report_dir,
                precomputed=precomputed,
                seeds=seeds,
                selected_ids=query_ids,
            )
            print()

        # === Archive ===
        print(_banner("Archiving"))

        fingerprints = collect_fingerprints(paths.output_dir)

        session_dir = archive_session(
            queries_dir=paths.output_dir, answers_dir=paths.generated_answers_dir,
            report_dir=paths.report_dir, results_base=paths.results_base,
        )

        write_session_manifest(
            session_dir,
            models=models,
            seeds=seeds,
            query_ids=query_ids,
            scale_factor=BENCHMARK_SCALE_FACTOR,
            generation_parameters={
                "temperature": LLM_TEMPERATURE,
                "max_tokens": LLM_MAX_TOKENS,
                "num_ctx": LLM_NUM_CTX,
            },
            prompt_flags=asdict(PROMPT_FLAGS),
            fingerprints=fingerprints,
            database_url=DATABASE_URL,
        )
        print("  ✓ Archived")
        print()

        elapsed = time.monotonic() - start_time
        print(format_run_summary(precomputed, models, session_dir, elapsed))

        return 0

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
