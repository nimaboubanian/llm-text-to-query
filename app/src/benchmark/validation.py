"""Validation checks for the benchmark pipeline."""

from pathlib import Path
from sqlalchemy import inspect, text
from typing import Tuple, Set

from benchmark.data_loader import TPCH_TABLES


def check_directory(directory: Path, extension: str, expected_count: int) -> None:
    """Check that a directory exists and contains the expected number of files.

    Raises:
        FileNotFoundError: If directory doesn't exist.
        ValueError: If file count doesn't match.
    """
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    files = list(directory.glob(f"*.{extension}"))
    if len(files) != expected_count:
        raise ValueError(
            f"Expected {expected_count} .{extension} files in {directory}, "
            f"found {len(files)}"
        )


def check_database_ready(db_url: str) -> bool:
    """Check if the database has the TPC-H schema loaded and tables non-empty.

    Returns True if ready, False if setup is needed.
    """
    from database.schema import create_engine_for_database

    engine = create_engine_for_database(db_url)
    try:
        inspector = inspect(engine)
        actual = {t.lower() for t in inspector.get_table_names()}
        expected = {t.lower() for t in TPCH_TABLES}

        if not expected.issubset(actual):
            return False

        # Fast non-empty check (avoid COUNT(*) on multi-million row tables)
        with engine.connect() as conn:
            for table in TPCH_TABLES:
                row = conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1")).fetchone()
                if row is None:
                    return False
    except Exception:
        return False

    return True


def check_data_cache(data_dir: Path) -> bool:
    """Check if all .tbl files exist and are non-empty."""
    if not data_dir.exists():
        return False
    return all(
        (data_dir / f"{t}.tbl").exists() and (data_dir / f"{t}.tbl").stat().st_size > 0
        for t in TPCH_TABLES
    )


def check_answers_completeness(
    answers_dir: Path,
    queries_dir: Path,
) -> Tuple[bool, Set[str]]:
    """Return (is_complete, missing_query_ids)."""
    expected = {q.stem for q in queries_dir.glob("*.sql")}
    if not answers_dir.exists():
        return False, expected
    actual = {a.stem for a in answers_dir.glob("*.csv")}
    missing = expected - actual
    return len(missing) == 0, missing
