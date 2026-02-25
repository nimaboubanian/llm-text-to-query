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
from text2query.benchmark.llm_benchmark import (
    run_llm_generation,
    execute_generated_queries,
)
from text2query.benchmark.reporting import (
    generate_reports,
    archive_session,
)


def main():
    from text2query.core.config import (
        DATABASE_URL,
        DEFAULT_MODEL,
        BENCHMARK_SCALE_FACTOR,
        BENCHMARK_DATA_PATH,
        BENCHMARK_SCHEMA_PATH,
        BENCHMARK_OUTPUT_DIR,
    )

    questions_dir = Path("benchmark/.tpch/questions")
    queries_dir = Path("benchmark/.tpch/queries")
    answers_dir = Path("benchmark/.tpch/answers")
    output_dir = Path(BENCHMARK_OUTPUT_DIR)
    generated_answers_dir = Path("benchmark/answers")
    report_dir = Path("benchmark/answers/report")
    results_base = Path("benchmark/results")
    data_dir = Path(BENCHMARK_DATA_PATH) if BENCHMARK_DATA_PATH else Path(f"benchmark/.tpch/data/sf{BENCHMARK_SCALE_FACTOR}")

    try:
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
            schema_file=Path(BENCHMARK_SCHEMA_PATH),
            scale_factor=BENCHMARK_SCALE_FACTOR
        )
        print()

        if not is_ready:
            print("Setup Database")
            setup_database(
                schema_file=Path(BENCHMARK_SCHEMA_PATH),
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

        print("\n--- LLM SQL Generation (model: {}) ---\n".format(DEFAULT_MODEL))

        print("Generate SQL Queries via LLM")
        run_llm_generation(
            questions_dir=questions_dir, output_dir=output_dir,
            db_url=DATABASE_URL, model=DEFAULT_MODEL,
        )
        print()

        print("Execute LLM-Generated Queries")
        execute_generated_queries(
            queries_dir=output_dir, answers_dir=generated_answers_dir, db_url=DATABASE_URL,
        )
        print()

        print("\n--- Analysis & Archiving ---\n")

        print("Generate Reports")
        generate_reports(
            generated_queries_dir=output_dir, reference_queries_dir=queries_dir,
            generated_answers_dir=generated_answers_dir, reference_answers_dir=answers_dir,
            report_dir=report_dir,
        )
        print()

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
        print(f"  - Model:           {DEFAULT_MODEL}")
        print(f"  - Database:        {DATABASE_URL}")
        print()

        return 0

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
