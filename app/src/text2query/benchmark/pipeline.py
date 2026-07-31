"""Stages: data generation, validation, database setup, and query execution."""
import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path

from sqlalchemy import inspect, text

from text2query.database.schema import create_engine_for_database
from text2query.database.executor import execute_sql_query

from text2query.benchmark.data_loader import TPCH_TABLES, load_tpch_data
from text2query.benchmark.fingerprint import read_manifest_fingerprint, write_manifest
from text2query.benchmark.progress import print_item_done, print_item_start

logger = logging.getLogger(__name__)


def read_business_question(qfile: Path) -> str | None:
    """Extract the NL business question from a benchmark question file."""
    if not qfile.exists():
        return None
    match = re.search(r'# Business Question:\s*\n\s*"(.+)"', qfile.read_text(), re.DOTALL)
    return match.group(1) if match else None


def _check_data_cache(data_dir: Path) -> bool:
    if not data_dir.exists():
        return False
    return all(
        (data_dir / f"{t}.tbl").exists() and (data_dir / f"{t}.tbl").stat().st_size > 0
        for t in TPCH_TABLES
    )


def generate_data(scale_factor: int, output_dir: Path) -> Path:
    if _check_data_cache(output_dir):
        print(f"  ✓ Using cached data: {output_dir}")
        return output_dir

    print(f"  Generating TPC-H data (scale factor: {scale_factor})...")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Running: uvx tpchgen-cli -s {scale_factor} --output-dir {output_dir}")

    result = subprocess.run(
        ["uvx", "tpchgen-cli>=2.0.1", "-s", str(scale_factor), "--output-dir", str(output_dir.resolve())],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Data generation failed: {result.stderr}")

    print(f"  ✓ Data generated: {output_dir}")
    return output_dir


def _check_directory(directory: Path, extension: str, expected_count: int) -> None:
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    files = list(directory.glob(f"*.{extension}"))
    if len(files) != expected_count:
        raise ValueError(
            f"Expected {expected_count} .{extension} files in {directory}, "
            f"found {len(files)}"
        )


def validate_directories(
    questions_dir: Path,
    queries_dir: Path
) -> None:
    print("  Validating directories...")
    _check_directory(questions_dir, "md", 22)
    print(f"  ✓ Questions: {questions_dir}")
    _check_directory(queries_dir, "sql", 22)
    print(f"  ✓ Queries: {queries_dir}")


def check_database_readiness(db_url: str, scale_factor: int = 1) -> bool:
    print("  Checking database readiness...")
    engine = create_engine_for_database(db_url)
    ready = False
    try:
        inspector = inspect(engine)
        actual = {t.lower() for t in inspector.get_table_names()}
        expected = {t.lower() for t in TPCH_TABLES}

        if expected.issubset(actual):
            # Fast non-empty check (avoid COUNT(*) on multi-million row tables), plus
            # exact-count checks on the small fixed/predictable-size tables — cheap even
            # at large scale factors — to catch a half-loaded or wrong-scale-factor DB.
            fixed_counts = {"nation": 25, "region": 5, "supplier": 10_000 * scale_factor}
            with engine.connect() as conn:
                ready = all(
                    conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1")).fetchone() is not None
                    for table in TPCH_TABLES
                ) and all(
                    conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() == count
                    for table, count in fixed_counts.items()
                )
    except Exception as e:
        logger.warning("Database readiness check failed: %s", e)

    print("  ✓ Database is ready" if ready else "  ✗ Database needs setup")
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


def load_schema(schema_file: Path, db_url: str) -> None:
    """Load the TPC-H schema DDL, terminating other backends holding locks first."""
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
    except Exception as e:
        raise RuntimeError(f"Failed to load schema: {e}")


def load_data(data_dir: Path, db_url: str) -> dict[str, int]:
    """Load TPC-H .tbl files into the database. Returns row counts per table."""
    try:
        return load_tpch_data(data_dir, db_url)
    except (FileNotFoundError, RuntimeError) as e:
        raise RuntimeError(f"Failed to load data: {e}")


def build_indexes(schema_file: Path, db_url: str) -> bool:
    """Build indexes from indexes.sql next to the schema file.

    Returns False (without error) if no indexes.sql exists — index creation
    is best-effort and non-fatal to the caller.
    """
    indexes_file = schema_file.parent / "indexes.sql"
    if not indexes_file.exists():
        return False

    engine = create_engine_for_database(db_url)
    indexes_sql = indexes_file.read_text()
    statements = [s.strip() for s in indexes_sql.split(";") if s.strip()]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
    return True


def setup_database(
    schema_file: Path,
    data_dir: Path,
    db_url: str,
) -> None:
    """Load schema, data, and indexes, narrating each step. Index failures are non-fatal."""
    print("  Loading database schema...")
    load_schema(schema_file, db_url)
    print("  ✓ Schema loaded")

    print("  Loading TPC-H data from .tbl files...")
    loaded_counts = load_data(data_dir, db_url)
    total_rows = sum(loaded_counts.values())
    print(f"  ✓ Loaded {total_rows:,} total rows into 8 tables")
    for table, count in sorted(loaded_counts.items()):
        print(f"    - {table}: {count:,} rows")

    print("  Building indexes...")
    try:
        built = build_indexes(schema_file, db_url)
    except Exception as e:
        print(f"  ⚠ Index creation failed (non-fatal): {e}")
    else:
        print("  ✓ Indexes built" if built else "  ⚠ No indexes.sql found, skipping index creation")


def generate_answers(
    queries_dir: Path,
    answers_dir: Path,
    db_url: str,
    scale_factor: int = 1,
) -> None:
    print("  Checking answer files...")

    query_files = sorted(queries_dir.glob("*.sql"))
    payload = json.dumps(
        {"scale_factor": scale_factor,
         "queries": {f.name: f.read_text() for f in query_files}},
        sort_keys=True,
    )
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()[:16]

    cached = read_manifest_fingerprint(answers_dir)
    if cached != fingerprint:
        # Fires even when cached is None, unlike runner.py's guard: the manifest is written
        # only after a fully successful regeneration, so a manifest-less answers/ (pre-fix,
        # or left by a crash) must revalidate or the staleness check never activates.
        print(f"  ⚠ Reference queries or scale factor changed — clearing stale ground truth in {answers_dir}")
        for f in answers_dir.glob("*.csv"):
            f.unlink()

    expected = {q.stem for q in query_files}
    actual = {a.stem for a in answers_dir.glob("*.csv")} if answers_dir.exists() else set()
    missing_ids = expected - actual

    if not missing_ids:
        print(f"  ✓ All {len(expected)} answer files exist")
        return

    print(f"  Generating {len(missing_ids)} missing answer files...")
    to_run = [queries_dir / f"{qid}.sql" for qid in sorted(missing_ids)]
    results = execute_queries_to_csv(to_run, answers_dir, db_url, write_error_file=False)

    failed = [r["query_id"] for r in results if r["status"] == "error"]
    if failed:
        raise RuntimeError(
            f"Ground-truth generation failed for queries: {', '.join(failed)} — "
            "benchmark cannot proceed with incomplete reference answers"
        )
    write_manifest(answers_dir, fingerprint, {"scale_factor": scale_factor, "queries": len(query_files)})


def execute_queries_to_csv(
    query_files: list[Path],
    output_dir: Path,
    db_url: str,
    *,
    write_error_file: bool = False,
    on_item_start=print_item_start,
    on_item_done=print_item_done,
) -> list[dict]:
    """Execute SQL files and save results as CSV.

    Args:
        query_files: .sql files to execute
        output_dir: directory for .csv results
        db_url: database connection URL
        write_error_file: on failure, write the error message to a sidecar .error file
        on_item_start: called as (index, total, label) before each query executes
        on_item_done: called with the outcome text after each query executes
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine_for_database(db_url)
    results = []

    for i, query_file in enumerate(query_files, 1):
        query_id = query_file.stem
        on_item_start(i, len(query_files), f"Q{query_id}")

        try:
            sql = query_file.read_text().strip()
            result = execute_sql_query(engine, sql)

            if not result.ok:
                if write_error_file:
                    (output_dir / f"{query_id}.error").write_text(result.error)
                on_item_done(" ✗ (error)")
                results.append({"query_id": query_id, "status": "error", "error": result.error})
            else:
                output_file = output_dir / f"{query_id}.csv"
                result.data.to_csv(output_file, index=False)
                on_item_done(f" ✓ ({len(result.data)} rows)")
                results.append({"query_id": query_id, "status": "success", "rows": len(result.data)})

        except Exception as e:
            if write_error_file:
                (output_dir / f"{query_id}.error").write_text(str(e))
            on_item_done(" ✗ (error)")
            results.append({"query_id": query_id, "status": "error", "error": str(e)})

    success = sum(1 for r in results if r["status"] == "success")
    errors = sum(1 for r in results if r["status"] == "error")
    print(f"  ✓ Executed {success} queries")
    if errors > 0:
        print(f"  ⚠ {errors} failed:")
        for r in results:
            if r["status"] == "error":
                print(f"    - Q{r['query_id']}: {r.get('error', 'Unknown')[:60]}")

    return results


