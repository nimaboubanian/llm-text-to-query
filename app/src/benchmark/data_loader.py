"""TPC-H data loading from .tbl files to PostgreSQL using COPY."""

import os
import subprocess
from pathlib import Path
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

# TPC-H tables in FK-dependency order
TPCH_TABLES = [
    'region', 'nation', 'part', 'supplier',
    'customer', 'partsupp', 'orders', 'lineitem',
]


def _fmt_size(nbytes: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def load_tpch_data(
    data_dir: Path,
    db_url: str,
    truncate: bool = False,
) -> dict[str, int]:
    """Load TPC-H .tbl files into PostgreSQL using COPY.

    Each table is loaded in its own transaction. The trailing pipe
    delimiter in .tbl files is stripped via sed before piping to COPY.

    Returns:
        Dictionary mapping table names to row counts loaded.
    """
    from database.schema import create_engine_for_database

    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    # Verify all .tbl files exist
    missing = [t for t in TPCH_TABLES if not (data_dir / f"{t}.tbl").exists()]
    if missing:
        raise FileNotFoundError(f"Missing .tbl files: {', '.join(missing)}")

    engine = create_engine_for_database(db_url)
    loaded = {}

    for i, table in enumerate(TPCH_TABLES, 1):
        tbl_file = data_dir / f"{table}.tbl"
        size = _fmt_size(os.path.getsize(tbl_file))
        print(f"  [{i}/{len(TPCH_TABLES)}] {table} ({size})...", end="", flush=True)

        with engine.begin() as conn:
            if truncate:
                conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))

            raw = conn.connection
            cur = raw.cursor()
            try:
                # sed strips the trailing pipe; output streams into COPY
                proc = subprocess.Popen(
                    ["sed", "s/|$//", str(tbl_file)],
                    stdout=subprocess.PIPE,
                )
                cur.copy_expert(
                    f"COPY {table} FROM STDIN WITH (FORMAT csv, DELIMITER '|', NULL '')",
                    proc.stdout,
                )
                proc.wait()
                if proc.returncode != 0:
                    raise RuntimeError(f"sed failed with exit code {proc.returncode}")
            except Exception as e:
                cur.close()
                raise RuntimeError(f"COPY failed for {table}: {e}")

            loaded[table] = cur.rowcount
            cur.close()

        print(f" ✓ {loaded[table]:,} rows", flush=True)
        logger.info(f"Loaded {loaded[table]:,} rows into {table}")

    return loaded
