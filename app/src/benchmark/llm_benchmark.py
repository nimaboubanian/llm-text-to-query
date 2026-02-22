"""LLM-driven benchmark steps: SQL generation and execution (steps 6–7)."""

import re
from pathlib import Path
from typing import List, Dict

from database.schema import create_engine_for_database, get_database_schema_string
from llm.service import get_sql_from_llm_streaming
from benchmark.pipeline import _execute_queries_to_csv


def step_6_run_core_benchmark(
    questions_dir: Path,
    output_dir: Path,
    db_url: str,
    model: str,
) -> List[Dict]:
    """Generate SQL via LLM for each question."""
    question_files = sorted(questions_dir.glob("*.md"))
    total = len(question_files)

    output_dir.mkdir(parents=True, exist_ok=True)

    existing = {f.stem for f in output_dir.glob("*.sql")}
    to_process = [q for q in question_files if q.stem not in existing]

    if not to_process:
        print(f"  ✓ All {total} queries already generated in {output_dir}")
        return []

    print(f"  🔨 Generating {len(to_process)}/{total} queries (skipping {len(existing)} cached)...")

    engine = create_engine_for_database(db_url)
    schema = get_database_schema_string(engine)

    results = []

    for i, qfile in enumerate(to_process, 1):
        query_id = qfile.stem
        content = qfile.read_text()

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
    """Execute LLM-generated SQL queries (with caching)."""

    query_files = sorted(queries_dir.glob("*.sql"))
    total = len(query_files)

    answers_dir.mkdir(parents=True, exist_ok=True)

    existing = {f.stem for f in answers_dir.glob("*.csv")}
    to_process = [q for q in query_files if q.stem not in existing]

    if not to_process:
        print(f"  ✓ All {total} answer files already exist in {answers_dir}")
        return []

    print(f"  🔨 Executing {len(to_process)}/{total} queries (skipping {len(existing)} cached)...")
    return _execute_queries_to_csv(to_process, answers_dir, db_url, write_error_csv=True)
