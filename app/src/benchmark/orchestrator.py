#!/usr/bin/env python3
"""Automated benchmark pipeline orchestrator."""

from pathlib import Path
import sys

from benchmark.pipeline import (
    step_1_generate_data,
    step_2_validate_directories,
    step_3_check_database_readiness,
    step_4_setup_database,
    step_5_generate_answers,
    step_6_run_core_benchmark,
    step_7_execute_generated_queries,
    step_8_generate_reports,
    step_9_archive_session,
)


def _phase_header(number: int, subtitle: str) -> None:
    print("=" * 60)
    print(f"  TPC-H Benchmark Pipeline - Phase {number}")
    print(f"  {subtitle}")
    print("=" * 60)
    print()


def _step_header(number: int, title: str) -> None:
    print(f"Step {number}: {title}")
    print("-" * 60)


def main():
    """Run the full benchmark pipeline (Phase 1 + Phase 2 + Phase 3)."""

    from core.config import (
        DATABASE_URL,
        DEFAULT_MODEL,
        BENCHMARK_SCALE_FACTOR,
        BENCHMARK_DATA_PATH,
        BENCHMARK_SCHEMA_PATH,
        BENCHMARK_OUTPUT_DIR,
    )

    # Define paths
    questions_dir = Path("benchmark/.tpch/questions")
    queries_dir = Path("benchmark/.tpch/queries")
    answers_dir = Path("benchmark/.tpch/answers")
    output_dir = Path(BENCHMARK_OUTPUT_DIR)
    generated_answers_dir = Path("benchmark/answers")
    report_dir = Path("benchmark/answers/report")
    results_base = Path("benchmark/results")
    data_dir = Path(BENCHMARK_DATA_PATH) if BENCHMARK_DATA_PATH else Path(f"benchmark/.tpch/data/sf{BENCHMARK_SCALE_FACTOR}")

    try:
        # ── Phase 1 ──────────────────────────────────────────────
        _phase_header(1, "Setup & Validation")

        _step_header(1, "Data Generation")
        if BENCHMARK_DATA_PATH:
            print(f"📁 Using existing data: {BENCHMARK_DATA_PATH}")
            data_dir = Path(BENCHMARK_DATA_PATH)
        else:
            print(f"🔨 Checking/Generating TPC-H data (scale factor: {BENCHMARK_SCALE_FACTOR})...")
            data_dir = step_1_generate_data(BENCHMARK_SCALE_FACTOR, data_dir)
        print()

        _step_header(2, "Validate Questions & Queries")
        step_2_validate_directories(questions_dir, queries_dir)
        print()

        _step_header(3, "Check Database Readiness")
        is_ready = step_3_check_database_readiness(
            db_url=DATABASE_URL,
            schema_file=Path(BENCHMARK_SCHEMA_PATH),
            scale_factor=BENCHMARK_SCALE_FACTOR
        )
        print()

        if not is_ready:
            _step_header(4, "Setup Database")
            step_4_setup_database(
                schema_file=Path(BENCHMARK_SCHEMA_PATH),
                data_dir=data_dir,
                db_url=DATABASE_URL,
                scale_factor=BENCHMARK_SCALE_FACTOR
            )
            print()
        else:
            print("Step 4: Skipped (Database already ready)")
            print()

        _step_header(5, "Generate Answer Files")
        step_5_generate_answers(queries_dir=queries_dir, answers_dir=answers_dir, db_url=DATABASE_URL)
        print()

        print("  ✓ Phase 1 Complete")
        print()

        # ── Phase 2 ──────────────────────────────────────────────
        _phase_header(2, f"LLM SQL Generation (model: {DEFAULT_MODEL})")

        _step_header(6, "Generate SQL Queries via LLM")
        step_6_run_core_benchmark(
            questions_dir=questions_dir, output_dir=output_dir,
            db_url=DATABASE_URL, model=DEFAULT_MODEL,
        )
        print()

        _step_header(7, "Execute LLM-Generated Queries")
        step_7_execute_generated_queries(
            queries_dir=output_dir, answers_dir=generated_answers_dir, db_url=DATABASE_URL,
        )
        print()

        # ── Phase 3 ──────────────────────────────────────────────
        _phase_header(3, "Analysis & Archiving")

        _step_header(8, "Generate Reports")
        step_8_generate_reports(
            generated_queries_dir=output_dir, reference_queries_dir=queries_dir,
            generated_answers_dir=generated_answers_dir, reference_answers_dir=answers_dir,
            report_dir=report_dir,
        )
        print()

        _step_header(9, "Archive Session")
        session_dir = step_9_archive_session(
            queries_dir=output_dir, answers_dir=generated_answers_dir,
            report_dir=report_dir, results_base=results_base,
        )
        print()

        # ── Summary ──────────────────────────────────────────────
        print("=" * 60)
        print("  ✓ Benchmark Complete")
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

    except FileNotFoundError as e:
        print(f"\n❌ Configuration Error: {e}", file=sys.stderr)
        print("\nPlease check that required files and directories exist.", file=sys.stderr)
        return 1

    except ValueError as e:
        print(f"\n❌ Validation Error: {e}", file=sys.stderr)
        return 1

    except RuntimeError as e:
        print(f"\n❌ Runtime Error: {e}", file=sys.stderr)
        print("\nCheck that docker compose services are running:", file=sys.stderr)
        print("  docker compose ps", file=sys.stderr)
        return 1

    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
