import os
import subprocess
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from text2query.database.schema import create_engine_for_database
from text2query.database.executor import execute_sql_query

from text2query.benchmark.validation import (
    check_directory,
    check_database_ready,
    check_data_cache,
    check_answers_completeness,
)

from text2query.benchmark.data_loader import load_tpch_data


def generate_data(scale_factor: int, output_dir: Path) -> Path:
    output_dir = output_dir or Path(f"benchmark/.tpch/data/sf{scale_factor}")

    if check_data_cache(output_dir):
        print(f"  ✓ Using cached data: {output_dir}")
        return output_dir

    print(f"  Generating TPC-H data (scale factor: {scale_factor})...")
    output_dir.mkdir(parents=True, exist_ok=True)

    cwd = Path("benchmark/.tpch").resolve()
    output_abs = output_dir.resolve()
    rel_path = os.path.relpath(output_abs, cwd)

    print(f"  Running: uv run tpchgen-cli -s {scale_factor} --output-dir {rel_path}")

    result = subprocess.run(
        ["uv", "run", "tpchgen-cli", "-s", str(scale_factor), "--output-dir", str(rel_path)],
        cwd="benchmark/.tpch",
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Data generation failed: {result.stderr}")

    print(f"  ✓ Data generated: {output_dir}")
    return output_dir


def validate_directories(
    questions_dir: Path,
    queries_dir: Path
) -> None:
    print("  Validating directories...")
    check_directory(questions_dir, "md", 22)
    print(f"  ✓ Questions: {questions_dir}")
    check_directory(queries_dir, "sql", 22)
    print(f"  ✓ Queries: {queries_dir}")


def check_database_readiness(db_url: str, **_) -> bool:
    print("  Checking database readiness...")
    ready = check_database_ready(db_url)
    if ready:
        print("  ✓ Database is ready")
    else:
        print("  ✗ Database needs setup")
    return ready


def _parse_schema_sql(schema_file: Path) -> list[str]:
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_file}")

    raw_statements = schema_file.read_text().split(";")
    statements = []
    for stmt in raw_statements:
        stmt = stmt.strip()
        if not stmt:
            continue
        lines = [line for line in stmt.split("\n")
                 if not line.strip().startswith("--")]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            statements.append(cleaned)
    return statements


def setup_database(
    schema_file: Path,
    data_dir: Path,
    db_url: str,
    scale_factor: int
) -> None:
    print("  Loading database schema...")

    statements = _parse_schema_sql(schema_file)
    engine = create_engine_for_database(db_url)

    try:
        with engine.begin() as conn:
            # Terminate other backends holding locks (e.g. app container's pool)
            conn.execute(text(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "  AND pid <> pg_backend_pid()"
            ))

            for statement in statements:
                conn.execute(text(statement))
        print("  ✓ Schema loaded")
    except Exception as e:
        raise RuntimeError(f"Failed to load schema: {e}")

    print("  Loading TPC-H data from .tbl files...")
    try:
        loaded_counts = load_tpch_data(data_dir, db_url)

        total_rows = sum(loaded_counts.values())
        print(f"  ✓ Loaded {total_rows:,} total rows into 8 tables")
        for table, count in sorted(loaded_counts.items()):
            print(f"    - {table}: {count:,} rows")

    except (FileNotFoundError, RuntimeError) as e:
        raise RuntimeError(f"Failed to load data: {e}")

    # Build indexes after loading (faster than during COPY)
    print("  Building indexes...")
    try:
        engine = create_engine_for_database(db_url)
        indexes_file = schema_file.parent / "indexes.sql"
        if not indexes_file.exists():
            print("  ⚠ No indexes.sql found, skipping index creation")
            return
        indexes_sql = indexes_file.read_text()
        statements = [s.strip() for s in indexes_sql.split(";") if s.strip()]
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
        print("  ✓ Indexes built")
    except Exception as e:
        print(f"  ⚠ Index creation failed (non-fatal): {e}")


def generate_answers(
    queries_dir: Path,
    answers_dir: Path,
    db_url: str
) -> list[dict]:
    print("  Checking answer files...")

    is_complete, missing_ids = check_answers_completeness(answers_dir, queries_dir)

    if is_complete:
        query_count = len(list(queries_dir.glob('*.sql')))
        print(f"  ✓ All {query_count} answer files exist")
        return []

    print(f"  Generating {len(missing_ids)} missing answer files...")
    query_files = [queries_dir / f"{qid}.sql" for qid in sorted(missing_ids)]
    return execute_queries_to_csv(query_files, answers_dir, db_url, write_error_csv=False)


def execute_queries_to_csv(
    query_files: list[Path],
    output_dir: Path,
    db_url: str,
    *,
    write_error_csv: bool = False,
) -> list[dict]:
    """Execute SQL files and save results as CSV.

    Args:
        query_files: .sql files to execute
        output_dir: directory for .csv results
        db_url: database connection URL
        write_error_csv: write error CSV on failure
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine_for_database(db_url)
    results = []

    for i, query_file in enumerate(query_files, 1):
        query_id = query_file.stem
        print(f"  [{i}/{len(query_files)}] Q{query_id}...", end="", flush=True)

        try:
            sql = query_file.read_text().strip()
            result_df = execute_sql_query(engine, sql)
            output_file = output_dir / f"{query_id}.csv"

            if isinstance(result_df, str):
                if write_error_csv:
                    pd.DataFrame({"ERROR": [result_df]}).to_csv(output_file, index=False)
                print(" ✗ (error)")
                results.append({"query_id": query_id, "status": "error", "error": result_df})
            else:
                result_df.to_csv(output_file, index=False)
                print(f" ✓ ({len(result_df)} rows)")
                results.append({"query_id": query_id, "status": "success", "rows": len(result_df)})

        except Exception as e:
            if write_error_csv:
                output_file = output_dir / f"{query_id}.csv"
                pd.DataFrame({"ERROR": [str(e)]}).to_csv(output_file, index=False)
            print(" ✗ (error)")
            results.append({"query_id": query_id, "status": "error", "error": str(e)})

    success = sum(1 for r in results if r["status"] == "success")
    errors = sum(1 for r in results if r["status"] == "error")
    print(f"  ✓ Executed {success} queries -> {output_dir}")
    if errors > 0:
        print(f"  ⚠ {errors} failed:")
        for r in results:
            if r["status"] == "error":
                print(f"    - Q{r['query_id']}: {r.get('error', 'Unknown')[:60]}")

    return results


