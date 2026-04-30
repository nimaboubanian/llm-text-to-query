#!/usr/bin/env python3

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
    model_slug,
)




def _run_single_model_benchmark(
    model: str,
    questions_dir: Path,
    queries_dir: Path,
    answers_dir: Path,
    output_base: Path,
    generated_answers_base: Path,
    report_base: Path,
    db_url: str,
    seeds: list[int] | None,
    multi_model: bool,
) -> Path:
    """Run the full benchmark (generate + execute + report) for one model."""
    if multi_model:
        slug = model_slug(model)
        output_dir = output_base / slug
        generated_answers_dir = generated_answers_base / slug
        report_dir = report_base / slug
    else:
        output_dir = output_base
        generated_answers_dir = generated_answers_base
        report_dir = report_base

    seed_info = f", seeds: {len(seeds)}" if seeds else ""
    print(f"\n--- LLM SQL Generation (model: {model}{seed_info}) ---\n")

    print("Generate SQL Queries via LLM")
    run_llm_generation(
        questions_dir=questions_dir, output_dir=output_dir,
        db_url=db_url, model=model,
        seeds=seeds,
    )
    print()

    print("Execute LLM-Generated Queries")
    execute_generated_queries(
        queries_dir=output_dir, answers_dir=generated_answers_dir, db_url=db_url,
        seeds=seeds,
    )
    print()

    print("Generate Reports")
    generate_reports(
        generated_queries_dir=output_dir, reference_queries_dir=queries_dir,
        generated_answers_dir=generated_answers_dir, reference_answers_dir=answers_dir,
        report_dir=report_dir,
        seeds=seeds,
        model=model,
    )
    print()

    return report_dir


def main():
    from text2query.core.config import (
        DATABASE_URL,
        DEFAULT_MODEL,
        BENCHMARK_SCALE_FACTOR,
        BENCHMARK_DATA_PATH,
        BENCHMARK_NUM_SEEDS,
        BENCHMARK_MODELS,
    )

    schema_file = Path("benchmark/.tpch/schema.sql")
    questions_dir = Path("benchmark/.tpch/questions")
    queries_dir = Path("benchmark/.tpch/queries")
    answers_dir = Path("benchmark/.tpch/answers")
    output_dir = Path("benchmark/queries")
    generated_answers_dir = Path("benchmark/answers")
    report_dir = Path("benchmark/reports")
    results_base = Path("benchmark/results")
    data_dir = Path(BENCHMARK_DATA_PATH) if BENCHMARK_DATA_PATH else Path(f"benchmark/.tpch/data/sf{BENCHMARK_SCALE_FACTOR}")

    seeds = list(range(1, BENCHMARK_NUM_SEEDS + 1)) if BENCHMARK_NUM_SEEDS > 1 else None
    models = BENCHMARK_MODELS if BENCHMARK_MODELS else [DEFAULT_MODEL]
    multi_model = len(models) > 1

    try:
        # === Phase 1: Setup (shared across all models) ===
        print("\n--- Setup & Validation ---\n")

        print("Data Generation")
        if BENCHMARK_DATA_PATH:
            print(f"  Using existing data: {BENCHMARK_DATA_PATH}")
            data_dir = Path(BENCHMARK_DATA_PATH)
        else:
            print(f"  Checking/Generating TPC-H data (scale factor: {BENCHMARK_SCALE_FACTOR})...")
            data_dir = generate_data(BENCHMARK_SCALE_FACTOR, data_dir)
        print()

        print("Validate Questions & Queries")
        validate_directories(questions_dir, queries_dir)
        print()

        print("Check Database Readiness")
        is_ready = check_database_readiness(
            db_url=DATABASE_URL,
            schema_file=schema_file,
            scale_factor=BENCHMARK_SCALE_FACTOR
        )
        print()

        if not is_ready:
            print("Setup Database")
            setup_database(
                schema_file=schema_file,
                data_dir=data_dir,
                db_url=DATABASE_URL,
                scale_factor=BENCHMARK_SCALE_FACTOR
            )
            print()
        else:
            print("Database already ready, skipping setup")
            print()

        print("Generate Answer Files")
        generate_answers(queries_dir=queries_dir, answers_dir=answers_dir, db_url=DATABASE_URL)
        print()

        # === Phase 2+3: Per-model benchmark ===
        if multi_model:
            print(f"\n{'=' * 60}")
            print(f"  Multi-Model Benchmark: {len(models)} models")
            print(f"{'=' * 60}\n")

        for i, model in enumerate(models, 1):
            if multi_model:
                print(f"\n{'=' * 60}")
                print(f"  Model {i}/{len(models)}: {model}")
                print(f"{'=' * 60}")

            _run_single_model_benchmark(
                model=model,
                questions_dir=questions_dir,
                queries_dir=queries_dir,
                answers_dir=answers_dir,
                output_base=output_dir,
                generated_answers_base=generated_answers_dir,
                report_base=report_dir,
                db_url=DATABASE_URL,
                seeds=seeds,
                multi_model=multi_model,
            )

        # === Cross-model comparison (if multi-model) ===
        if multi_model:
            print("\n--- Cross-Model Comparison ---\n")
            generate_cross_model_report(
                models=models,
                reference_queries_dir=queries_dir,
                reference_answers_dir=answers_dir,
                generated_queries_base=output_dir,
                generated_answers_base=generated_answers_dir,
                report_dir=report_dir,
                seeds=seeds,
            )
            print()

        # === Archive ===
        print("\n--- Archiving ---\n")

        print("Archive Session")
        session_dir = archive_session(
            queries_dir=output_dir, answers_dir=generated_answers_dir,
            report_dir=report_dir, results_base=results_base,
        )
        print()

        print("=" * 60)
        print("  Benchmark Complete")
        print("=" * 60)
        print()
        print("Summary:")
        print(f"  - Questions:       {len(list(questions_dir.glob('*.md')))} files")
        print(f"  - Ground truth:    {len(list(queries_dir.glob('*.sql')))} queries")
        print(f"  - Reference ans:   {len(list(answers_dir.glob('*.csv')))} files")
        print(f"  - Session:         {session_dir}")
        if multi_model:
            print(f"  - Models:          {', '.join(models)}")
        else:
            print(f"  - Model:           {models[0]}")
        if seeds:
            print(f"  - Seeds:           {BENCHMARK_NUM_SEEDS} ({seeds})")
        print(f"  - Database:        {DATABASE_URL}")
        print()

        return 0

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
