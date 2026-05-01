import re
from pathlib import Path

from text2query.database.schema import create_engine_for_database, get_database_schema_string
from text2query.llm.service import get_sql_from_llm_streaming
from text2query.benchmark.pipeline import execute_queries_to_csv


def run_llm_generation(
    questions_dir: Path,
    output_dir: Path,
    db_url: str,
    model: str,
    seeds: list[int] | None = None,
    query_ids: list[str] | None = None,
) -> list[dict]:
    if seeds and len(seeds) > 1:
        all_results = []
        for seed in seeds:
            seed_dir = output_dir / f"seed_{seed}"
            print(f"\n  --- Seed {seed} ---")
            results = _run_single_generation(
                questions_dir, seed_dir, db_url, model, seed=seed, query_ids=query_ids,
            )
            all_results.extend(
                {**r, "seed": seed} for r in results
            )
        return all_results
    else:
        seed = seeds[0] if seeds else None
        return _run_single_generation(
            questions_dir, output_dir, db_url, model, seed=seed, query_ids=query_ids,
        )


def _run_single_generation(
    questions_dir: Path,
    output_dir: Path,
    db_url: str,
    model: str,
    seed: int | None = None,
    query_ids: list[str] | None = None,
) -> list[dict]:
    question_files = sorted(questions_dir.glob("*.md"))
    if query_ids is not None:
        question_files = [q for q in question_files if q.stem in query_ids]
    total = len(question_files)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Cache: skip queries whose .sql file already exists. Assumes model/prompt/schema
    # haven't changed since the file was generated — safe for resuming interrupted runs.
    existing = {f.stem for f in output_dir.glob("*.sql")}
    to_process = [q for q in question_files if q.stem not in existing]

    if not to_process:
        print(f"  ✓ All {total} queries already generated in {output_dir}")
        return []

    seed_label = f" (seed={seed})" if seed is not None else ""
    print(f"  Generating {len(to_process)}/{total} queries{seed_label} (skipping {len(existing)} cached)...")

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

        for chunk in get_sql_from_llm_streaming(question, schema, model, seed=seed):
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
    print(f"  ✓ Generated {success} queries -> {output_dir}")
    if errors > 0:
        print(f"  ⚠ {errors} failed:")
        for r in results:
            if r["status"] == "error":
                print(f"    - Q{r['query_id']}: {r.get('error', 'Unknown')[:60]}")

    return results


def execute_generated_queries(
    queries_dir: Path,
    answers_dir: Path,
    db_url: str,
    seeds: list[int] | None = None,
    query_ids: list[str] | None = None,
) -> list[dict]:
    if seeds and len(seeds) > 1:
        all_results = []
        for seed in seeds:
            seed_queries = queries_dir / f"seed_{seed}"
            seed_answers = answers_dir / f"seed_{seed}"
            print(f"\n  --- Seed {seed} ---")
            results = _execute_single(seed_queries, seed_answers, db_url, query_ids=query_ids)
            all_results.extend(
                {**r, "seed": seed} for r in results
            )
        return all_results
    else:
        return _execute_single(queries_dir, answers_dir, db_url, query_ids=query_ids)


def _execute_single(
    queries_dir: Path,
    answers_dir: Path,
    db_url: str,
    query_ids: list[str] | None = None,
) -> list[dict]:
    query_files = sorted(queries_dir.glob("*.sql"))
    if query_ids is not None:
        query_files = [q for q in query_files if q.stem in query_ids]
    total = len(query_files)

    answers_dir.mkdir(parents=True, exist_ok=True)

    existing = {f.stem for f in answers_dir.glob("*.csv")}
    to_process = [q for q in query_files if q.stem not in existing]

    if not to_process:
        print(f"  ✓ All {total} answer files already exist in {answers_dir}")
        return []

    print(f"  Executing {len(to_process)}/{total} queries (skipping {len(existing)} cached)...")
    return execute_queries_to_csv(to_process, answers_dir, db_url, write_error_csv=True)
