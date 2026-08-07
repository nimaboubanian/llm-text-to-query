#!/usr/bin/env python3
"""Benchmark CLI entry point: orchestrates the full evaluation pipeline end to end."""

from dataclasses import asdict, dataclass
import logging
import time
from pathlib import Path
import sys

from backend.benchmark.pipeline import (
    ensure_database_exists,
    generate_data,
    validate_directories,
    check_database_readiness,
    setup_database,
    generate_answers,
)
from backend.benchmark.runner import (
    run_llm_generation,
    execute_generated_queries,
)
from backend.benchmark.reporting import (
    generate_reports,
    generate_cross_model_report,
    archive_session,
    write_session_manifest,
    format_run_summary,
    format_session_header,
)
from backend.benchmark.fingerprint import collect_fingerprints
from backend.llm.ollama import is_cloud_model


def _banner(title: str) -> str:
    """Render a light section divider padded to 60 columns, matching the header/footer width."""
    prefix = f"─── {title} "
    return prefix + "─" * max(3, 60 - len(prefix))


def _sort_locals_first(models: list[str]) -> list[str]:
    """Order local models ahead of Ollama Cloud ones, stable within each group.

    A cloud quota abort ends the run wherever it lands, so anything queued after
    the exhausted model is lost. Running locals first makes that loss provably
    cloud-only, and `sorted` is stable so the user's ordering still decides which
    local — and which cloud — model goes first.
    """
    return sorted(models, key=is_cloud_model)


@dataclass(frozen=True)
class BenchmarkPaths:
    """Filesystem layout for a benchmark run."""
    # tpch/* resolves under app/ and benchmark_results/* under the repo root;
    # they only coincide because compose mounts both at /app in-container.
    schema_file: Path = Path("tpch/schema.sql")
    questions_dir: Path = Path("tpch/questions")
    queries_dir: Path = Path("tpch/queries")
    answers_dir: Path = Path("tpch/answers")
    output_dir: Path = Path("benchmark_results/queries")
    generated_answers_dir: Path = Path("benchmark_results/answers")
    report_dir: Path = Path("benchmark_results/reports")
    results_base: Path = Path("benchmark_results")


def _run_single_model_benchmark(
    model: str,
    paths: BenchmarkPaths,
    db_url: str,
    seeds: list[int] | None,
    query_ids: list[str] | None = None,
) -> tuple[list[dict], bool]:
    """Run the full benchmark (generate + execute + report) for one model.

    Returns (results, aborted). `aborted` is True when an Ollama Cloud quota abort cut
    generation short — execution and reporting still run, so the completed work is
    scored and written before the caller stops the session.
    """
    slug = model.replace(":", "_").replace("/", "_")
    output_dir = paths.output_dir / slug
    generated_answers_dir = paths.generated_answers_dir / slug
    report_dir = paths.report_dir / slug

    print(_banner("SQL Generation"))
    aborted = bool(run_llm_generation(
        questions_dir=paths.questions_dir, output_dir=output_dir,
        db_url=db_url, model=model,
        seeds=seeds, query_ids=query_ids,
    ))
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

    return results, aborted


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
    from backend.core.config import (
        BENCHMARK_DATABASE_URL,
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
    data_dir = Path(BENCHMARK_DATA_PATH) if BENCHMARK_DATA_PATH else Path(f"tpch/data/sf{BENCHMARK_SCALE_FACTOR}")

    seeds = list(range(1, BENCHMARK_NUM_SEEDS + 1))
    models = _sort_locals_first(BENCHMARK_MODELS)
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
            database_url=BENCHMARK_DATABASE_URL,
        ))

        if skipped:
            print(f"  ⚠ Unknown query IDs (skipped): {', '.join(skipped)}")
        if BENCHMARK_SCALE_FACTOR != 1:
            print("  ⚠ BENCHMARK_SCALE_FACTOR != 1: reference query 11 hardcodes the SF1 "
                  "fraction (0.0001); its ground truth is wrong at this scale")
        if query_ids is not None and not query_ids:
            print("  ✗ No valid query IDs remain after filtering — aborting")
            sys.exit(1)
        if not models:
            print("  ✗ No models configured (BENCHMARK_MODELS is empty) — aborting")
            sys.exit(1)
        if skipped or BENCHMARK_SCALE_FACTOR != 1:
            print()

        # === Phase 1: Setup (shared across all models) ===
        print(_banner("Setup"))
        if ensure_database_exists(BENCHMARK_DATABASE_URL):
            print("  ✓ Created benchmark database")

        if BENCHMARK_DATA_PATH:
            print(f"  Using existing data: {BENCHMARK_DATA_PATH}")
        else:
            data_dir = generate_data(BENCHMARK_SCALE_FACTOR, data_dir)

        validate_directories(paths.questions_dir, paths.queries_dir)

        if not check_database_readiness(db_url=BENCHMARK_DATABASE_URL, scale_factor=BENCHMARK_SCALE_FACTOR):
            setup_database(
                schema_file=paths.schema_file,
                data_dir=data_dir,
                db_url=BENCHMARK_DATABASE_URL,
            )

        generate_answers(
            queries_dir=paths.queries_dir, answers_dir=paths.answers_dir,
            db_url=BENCHMARK_DATABASE_URL, scale_factor=BENCHMARK_SCALE_FACTOR,
        )
        print()

        # === Phase 2+3: Per-model benchmark ===
        precomputed = {}
        skipped_models: list[str] = []
        for i, model in enumerate(models, 1):
            if multi_model:
                print("═" * 60)
                print(f"  Model {i}/{len(models)}: {model}")
                print("═" * 60)
                print()

            results, aborted = _run_single_model_benchmark(
                model=model,
                paths=paths,
                db_url=BENCHMARK_DATABASE_URL,
                seeds=seeds,
                query_ids=query_ids,
            )
            precomputed[model] = results

            if aborted:
                # Quota windows are hourly, so there is nothing to wait for. Locals ran
                # first, so everything still queued is a cloud model that would 429 too.
                skipped_models = models[i:]
                if skipped_models:
                    print(f"  ⊘ Not run (rate-limited): {', '.join(skipped_models)}")
                    print()
                break

        # === Cross-model comparison (models that produced results) ===
        ran_models = list(precomputed)
        if len(ran_models) > 1:
            print(_banner("Cross-Model Comparison"))
            generate_cross_model_report(
                models=ran_models,
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
            database_url=BENCHMARK_DATABASE_URL,
            skipped_models=skipped_models,
        )
        print("  ✓ Archived")
        print()

        elapsed = time.monotonic() - start_time
        print(format_run_summary(
            precomputed, ran_models, session_dir, elapsed, skipped_models=skipped_models,
        ))

        return 0

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
