"""Individual pipeline step implementations for automated benchmark."""

import subprocess
import re
from pathlib import Path
from typing import List, Dict, Set
from sqlalchemy import text

from database.schema import create_engine_for_database, get_database_schema_string
from database.executor import execute_sql_query
from llm.service import get_sql_from_llm_streaming

from benchmark.validation import (
    check_directory,
    check_database_ready,
    check_data_cache,
    check_answers_completeness,
)

# Import data loader
from benchmark.data_loader import load_tpch_data


def step_1_generate_data(scale_factor: int, output_dir: Path) -> Path:
    """Generate TPC-H data using tpchgen-cli with caching check.

    Args:
        scale_factor: TPC-H scale factor (1, 10, 100, 1000)
        output_dir: Directory to save generated data

    Returns:
        Path to generated data directory

    Raises:
        RuntimeError: If data generation fails
    """
    output_dir = output_dir or Path(f"benchmark/.tpch/data/sf{scale_factor}")

    # Check cache first
    if check_data_cache(output_dir):
        print(f"  ✓ Using cached data: {output_dir}")
        return output_dir

    print(f"  🔨 Generating TPC-H data (scale factor: {scale_factor})...")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Calculate relative path from benchmark/.tpch to output_dir
    # If output_dir is /app/benchmark/data/sf1, and we're in /app/benchmark/.tpch
    # we need to pass ../data/sf1 as the output directory
    import os
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


def step_2_validate_directories(
    questions_dir: Path,
    queries_dir: Path
) -> None:
    """Validate questions and queries directories."""
    print("  📁 Validating directories...")
    check_directory(questions_dir, "md", 22)
    print(f"  ✓ Questions: {questions_dir}")
    check_directory(queries_dir, "sql", 22)
    print(f"  ✓ Queries: {queries_dir}")


def step_3_check_database_readiness(db_url: str, **_) -> bool:
    """Check if database has schema loaded and data present."""
    print("  🗄️  Checking database readiness...")
    ready = check_database_ready(db_url)
    if ready:
        print("  ✓ Database is ready")
    else:
        print("  ✗ Database needs setup")
    return ready


def step_4_setup_database(
    schema_file: Path,
    data_dir: Path,
    db_url: str,
    scale_factor: int
) -> None:
    """Setup database: load schema and data.

    Args:
        schema_file: Path to schema.sql file
        data_dir: Directory containing .tbl files
        db_url: Database connection URL
        scale_factor: Scale factor for validation

    Raises:
        FileNotFoundError: If schema or data files missing
        RuntimeError: If setup fails
    """
    print("  📋 Loading database schema...")

    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_file}")

    schema_sql = schema_file.read_text()
    engine = create_engine_for_database(db_url)

    # Split by semicolons and filter out comments/empty statements
    raw_statements = schema_sql.split(';')
    statements = []
    for stmt in raw_statements:
        # Remove leading/trailing whitespace
        stmt = stmt.strip()
        # Skip empty statements
        if not stmt:
            continue
        # Skip SQL comments (-- at start of line)
        lines = [line for line in stmt.split('\n')
                 if not line.strip().startswith('--')]
        cleaned = '\n'.join(lines).strip()
        if cleaned:
            statements.append(cleaned)

    try:
        with engine.begin() as conn:
            # Terminate other backends that may hold locks on these tables
            # (e.g. the always-on 'app' container's connection pool)
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

    print("  📥 Loading TPC-H data from .tbl files...")
    try:
        loaded_counts = load_tpch_data(data_dir, db_url)

        # Print summary
        total_rows = sum(loaded_counts.values())
        print(f"  ✓ Loaded {total_rows:,} total rows into 8 tables")
        for table, count in sorted(loaded_counts.items()):
            print(f"    - {table}: {count:,} rows")

    except (FileNotFoundError, RuntimeError) as e:
        raise RuntimeError(f"Failed to load data: {e}")

    # Build indexes AFTER data loading (bulk build is much faster than
    # maintaining indexes during COPY)
    print("  📇 Building indexes...")
    try:
        engine = create_engine_for_database(db_url)
        with engine.begin() as conn:
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_lineitem_orderkey   ON lineitem (l_orderkey)",
                "CREATE INDEX IF NOT EXISTS idx_lineitem_partkey    ON lineitem (l_partkey)",
                "CREATE INDEX IF NOT EXISTS idx_lineitem_suppkey    ON lineitem (l_suppkey)",
                "CREATE INDEX IF NOT EXISTS idx_lineitem_shipdate   ON lineitem (l_shipdate)",
                "CREATE INDEX IF NOT EXISTS idx_lineitem_part_supp_ship ON lineitem (l_partkey, l_suppkey, l_shipdate)",
                "CREATE INDEX IF NOT EXISTS idx_orders_custkey      ON orders   (o_custkey)",
                "CREATE INDEX IF NOT EXISTS idx_orders_orderdate    ON orders   (o_orderdate)",
                "CREATE INDEX IF NOT EXISTS idx_partsupp_suppkey    ON partsupp (ps_suppkey)",
                "CREATE INDEX IF NOT EXISTS idx_customer_nationkey  ON customer (c_nationkey)",
                "CREATE INDEX IF NOT EXISTS idx_supplier_nationkey  ON supplier (s_nationkey)",
                "CREATE INDEX IF NOT EXISTS idx_nation_regionkey    ON nation   (n_regionkey)",
            ]
            for idx_sql in indexes:
                conn.execute(text(idx_sql))
        print("  ✓ Indexes built")
    except Exception as e:
        print(f"  ⚠ Index creation failed (non-fatal): {e}")


def step_5_generate_answers(
    queries_dir: Path,
    answers_dir: Path,
    db_url: str
) -> List[Dict]:
    """Generate answer CSV files from SQL queries.

    Args:
        queries_dir: Directory containing .sql query files
        answers_dir: Directory to save .csv answer files
        db_url: Database connection URL

    Returns:
        List of generation results

    Raises:
        RuntimeError: If answer generation fails
    """
    print("  📝 Checking answer files...")

    # Check completeness
    is_complete, missing_ids = check_answers_completeness(answers_dir, queries_dir)

    if is_complete:
        query_count = len(list(queries_dir.glob('*.sql')))
        print(f"  ✓ All {query_count} answer files exist")
        return []

    print(f"  🔨 Generating {len(missing_ids)} missing answer files...")

    # Create directory if needed
    answers_dir.mkdir(parents=True, exist_ok=True)

    # Determine which queries to process
    query_files = [queries_dir / f"{qid}.sql" for qid in sorted(missing_ids)]

    engine = create_engine_for_database(db_url)
    results = []

    for query_file in query_files:
        query_id = query_file.stem
        try:
            query = query_file.read_text()
            result_df = execute_sql_query(engine, query)

            if isinstance(result_df, str):
                results.append({'query_id': query_id, 'status': 'error', 'error': result_df})
                continue

            output_file = answers_dir / f"{query_id}.csv"
            result_df.to_csv(output_file, index=False)
            results.append({'query_id': query_id, 'status': 'success', 'rows': len(result_df)})

        except Exception as e:
            results.append({'query_id': query_id, 'status': 'error', 'error': str(e)})

    # Report results
    success_count = sum(1 for r in results if r['status'] == 'success')
    error_count = sum(1 for r in results if r['status'] == 'error')

    print(f"  ✓ Generated {success_count} answer files")
    if error_count > 0:
        print(f"  ⚠ {error_count} queries failed:")
        for r in results:
            if r['status'] == 'error':
                error_msg = r.get('error', 'Unknown error')
                print(f"    - Query {r['query_id']}: {error_msg[:60]}...")

    return results


def step_6_run_core_benchmark(
    questions_dir: Path,
    output_dir: Path,
    db_url: str,
    model: str,
) -> List[Dict]:
    """Send each business question to the LLM and save the generated SQL.

    Skips questions that already have a generated .sql file in output_dir.

    Returns:
        List of result dicts with query_id, status, and error (if any).
    """
    question_files = sorted(questions_dir.glob("*.md"))
    total = len(question_files)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Check which queries already exist (caching)
    existing = {f.stem for f in output_dir.glob("*.sql")}
    to_process = [q for q in question_files if q.stem not in existing]

    if not to_process:
        print(f"  ✓ All {total} queries already generated in {output_dir}")
        return []

    print(f"  🔨 Generating {len(to_process)}/{total} queries (skipping {len(existing)} cached)...")

    # Get database schema once
    engine = create_engine_for_database(db_url)
    schema = get_database_schema_string(engine)

    results = []

    for i, qfile in enumerate(to_process, 1):
        query_id = qfile.stem
        content = qfile.read_text()

        # Extract business question (format: # Business Question:\n"question")
        match = re.search(r'# Business Question:\s*\n\s*"([^"]+)"', content)
        if not match:
            print(f"  [{i}/{len(to_process)}] Q{query_id}... ⚠ no question found, skipping")
            continue

        question = match.group(1)

        print(f"  [{i}/{len(to_process)}] Q{query_id}...", end="", flush=True)

        generated_sql = None
        error = None

        for chunk in get_sql_from_llm_streaming(question, schema, "postgresql", model):
            if chunk["type"] == "done":
                generated_sql = chunk.get("sql")
                break
            elif chunk["type"] == "error":
                error = chunk.get("message")
                break

        if generated_sql:
            output_file = output_dir / f"{query_id}.sql"
            output_file.write_text(generated_sql)
            print(" ✓")
            results.append({"query_id": query_id, "status": "success"})
        else:
            print(" ✗")
            results.append({"query_id": query_id, "status": "error", "error": error or "No SQL generated"})

    # Summary
    success = sum(1 for r in results if r["status"] == "success")
    errors = sum(1 for r in results if r["status"] == "error")
    print(f"  ✓ Generated {success} queries → {output_dir}")
    if errors > 0:
        print(f"  ⚠ {errors} failed:")
        for r in results:
            if r["status"] == "error":
                print(f"    - Q{r['query_id']}: {r.get('error', 'Unknown')[:60]}")

    return results


def step_7_execute_generated_queries(
    queries_dir: Path,
    answers_dir: Path,
    db_url: str,
) -> List[Dict]:
    """Execute LLM-generated SQL queries and save results as CSV.

    Failed queries get a CSV with an ERROR column for easy detection.
    Skips queries that already have a .csv in answers_dir.

    Returns:
        List of result dicts with query_id and status.
    """
    import pandas as pd

    query_files = sorted(queries_dir.glob("*.sql"))
    total = len(query_files)

    answers_dir.mkdir(parents=True, exist_ok=True)

    # Caching: skip queries that already have a CSV
    existing = {f.stem for f in answers_dir.glob("*.csv")}
    to_process = [q for q in query_files if q.stem not in existing]

    if not to_process:
        print(f"  ✓ All {total} answer files already exist in {answers_dir}")
        return []

    print(f"  🔨 Executing {len(to_process)}/{total} queries (skipping {len(existing)} cached)...")

    engine = create_engine_for_database(db_url)
    results = []

    for i, query_file in enumerate(to_process, 1):
        query_id = query_file.stem
        print(f"  [{i}/{len(to_process)}] Q{query_id}...", end="", flush=True)

        try:
            sql = query_file.read_text().strip()
            result_df = execute_sql_query(engine, sql)

            output_file = answers_dir / f"{query_id}.csv"

            if isinstance(result_df, str):
                # execute_sql_query returns error string on failure
                pd.DataFrame({"ERROR": [result_df]}).to_csv(output_file, index=False)
                print(" ✗ (error)")
                results.append({"query_id": query_id, "status": "error", "error": result_df})
            else:
                result_df.to_csv(output_file, index=False)
                print(f" ✓ ({len(result_df)} rows)")
                results.append({"query_id": query_id, "status": "success", "rows": len(result_df)})

        except Exception as e:
            output_file = answers_dir / f"{query_id}.csv"
            pd.DataFrame({"ERROR": [str(e)]}).to_csv(output_file, index=False)
            print(" ✗ (error)")
            results.append({"query_id": query_id, "status": "error", "error": str(e)})

    # Summary
    success = sum(1 for r in results if r["status"] == "success")
    errors = sum(1 for r in results if r["status"] == "error")
    print(f"  ✓ Executed {success} queries → {answers_dir}")
    if errors > 0:
        print(f"  ⚠ {errors} failed (error details saved in CSV):")
        for r in results:
            if r["status"] == "error":
                print(f"    - Q{r['query_id']}: {r.get('error', 'Unknown')[:60]}")

    return results


def step_4_evaluate_similarity(
    generated_dir: Path,
    reference_dir: Path,
    answers_dir: Path,
) -> List[Dict]:
    """Evaluate SQL similarity (stub for now).

    Args:
        generated_dir: Directory with generated SQL files
        reference_dir: Directory with reference SQL files
        answers_dir: Directory with expected result files

    Returns:
        Empty list (stub - scaffold for future)
    """
    # STUB IMPLEMENTATION
    # This is where similarity evaluation will eventually happen
    # For now, just return empty list to satisfy the interface

    # TODO: Implement SQL similarity evaluation
    # - Compare SQL syntax
    # - Compare result sets
    # - Calculate metrics (precision, recall, F1, Jaccard, etc.)

    return []


def step_8_generate_reports(
    generated_queries_dir: Path,
    reference_queries_dir: Path,
    generated_answers_dir: Path,
    reference_answers_dir: Path,
    report_dir: Path,
) -> Path:
    """Generate per-query markdown report files (scaffold).

    Creates a summary.md and a per-query report for each of the 22 queries.
    Actual analysis logic will be implemented in a future commit.

    Returns:
        Path to the report directory.
    """
    per_query_dir = report_dir / "per_query"
    per_query_dir.mkdir(parents=True, exist_ok=True)

    query_ids = sorted(
        f.stem for f in reference_queries_dir.glob("*.sql")
    )

    for qid in query_ids:
        has_generated = (generated_queries_dir / f"{qid}.sql").exists()
        has_answer = (generated_answers_dir / f"{qid}.csv").exists()

        # Check if the answer is an error file
        is_error = False
        if has_answer:
            first_line = (generated_answers_dir / f"{qid}.csv").read_text().split("\n", 1)[0]
            is_error = first_line.strip() == "ERROR"

        status = "✗ error" if is_error else ("✓ executed" if has_answer else "✗ not generated")

        report = (
            f"# Query {qid} — Report\n\n"
            f"- **Status:** {status}\n"
            f"- **LLM query generated:** {'yes' if has_generated else 'no'}\n"
            f"- **LLM answer produced:** {'yes' if has_answer and not is_error else 'no'}\n"
            f"\n> Detailed similarity analysis will be added in a future update.\n"
        )
        (per_query_dir / f"{qid}.md").write_text(report)
        print(f"  [{qid}] {status}")

    # Summary report
    total = len(query_ids)
    executed = sum(
        1 for qid in query_ids
        if (generated_answers_dir / f"{qid}.csv").exists()
        and (generated_answers_dir / f"{qid}.csv").read_text().split("\n", 1)[0].strip() != "ERROR"
    )
    errors = sum(
        1 for qid in query_ids
        if (generated_answers_dir / f"{qid}.csv").exists()
        and (generated_answers_dir / f"{qid}.csv").read_text().split("\n", 1)[0].strip() == "ERROR"
    )
    not_generated = total - executed - errors

    summary = (
        f"# Benchmark Summary\n\n"
        f"| Metric | Count |\n"
        f"|---|---|\n"
        f"| Total queries | {total} |\n"
        f"| Executed successfully | {executed} |\n"
        f"| Execution errors | {errors} |\n"
        f"| Not generated | {not_generated} |\n"
        f"\n> Detailed similarity metrics will be added in a future update.\n"
    )
    (report_dir / "summary.md").write_text(summary)

    print(f"  ✓ Reports generated → {report_dir}")
    return report_dir


def step_9_archive_session(
    queries_dir: Path,
    answers_dir: Path,
    report_dir: Path,
    results_base: Path,
) -> Path:
    """Archive generated queries, answers, and reports into a timestamped directory.

    Creates benchmark/results/YYYY-MM-DD_HH-MM-SS/ and moves everything into it,
    then removes the source directories entirely for a clean benchmark folder.

    Returns:
        Path to the created session directory.
    """
    import shutil
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_dir = results_base / timestamp

    session_queries = session_dir / "queries"
    session_answers = session_dir / "answers"
    session_report = session_dir / "report"

    session_queries.mkdir(parents=True, exist_ok=True)
    session_answers.mkdir(parents=True, exist_ok=True)

    # Move queries
    query_files = list(queries_dir.glob("*.sql"))
    for f in query_files:
        shutil.move(str(f), str(session_queries / f.name))
    print(f"  📂 Moved {len(query_files)} queries → {session_queries}")

    # Move answers
    answer_files = list(answers_dir.glob("*.csv"))
    for f in answer_files:
        shutil.move(str(f), str(session_answers / f.name))
    print(f"  📂 Moved {len(answer_files)} answers → {session_answers}")

    # Move reports
    if report_dir.exists():
        shutil.copytree(str(report_dir), str(session_report), dirs_exist_ok=True)
        shutil.rmtree(str(report_dir))
        print(f"  📂 Moved reports → {session_report}")

    # Clean up: remove source directories entirely
    for d in [queries_dir, answers_dir]:
        if d.exists():
            shutil.rmtree(str(d))

    print(f"  ✓ Session archived → {session_dir}")
    return session_dir

