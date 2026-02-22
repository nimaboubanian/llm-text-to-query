"""Benchmark reporting and session archiving (steps 8-9)."""

import shutil
from datetime import datetime
from pathlib import Path


def step_8_generate_reports(
    generated_queries_dir: Path,
    reference_queries_dir: Path,
    generated_answers_dir: Path,
    reference_answers_dir: Path,
    report_dir: Path,
) -> Path:
    """Generate summary.md and per-query reports."""
    per_query_dir = report_dir / "per_query"
    per_query_dir.mkdir(parents=True, exist_ok=True)

    query_ids = sorted(
        f.stem for f in reference_queries_dir.glob("*.sql")
    )

    executed = 0
    errors = 0

    for qid in query_ids:
        has_generated = (generated_queries_dir / f"{qid}.sql").exists()
        has_answer = (generated_answers_dir / f"{qid}.csv").exists()

        is_error = False
        if has_answer:
            first_line = (generated_answers_dir / f"{qid}.csv").read_text().split("\n", 1)[0]
            is_error = first_line.strip() == "ERROR"

        status = "✗ error" if is_error else ("✓ executed" if has_answer else "✗ not generated")

        if is_error:
            errors += 1
        elif has_answer:
            executed += 1

        report = (
            f"# Query {qid} — Report\n\n"
            f"- **Status:** {status}\n"
            f"- **LLM query generated:** {'yes' if has_generated else 'no'}\n"
            f"- **LLM answer produced:** {'yes' if has_answer and not is_error else 'no'}\n"
            f"\n> Detailed similarity analysis will be added in a future update.\n"
        )
        (per_query_dir / f"{qid}.md").write_text(report)
        print(f"  [{qid}] {status}")

    total = len(query_ids)
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
    """Archive session to timestamped directory and clean up sources."""

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_dir = results_base / timestamp

    session_queries = session_dir / "queries"
    session_answers = session_dir / "answers"
    session_report = session_dir / "report"

    session_queries.mkdir(parents=True, exist_ok=True)
    session_answers.mkdir(parents=True, exist_ok=True)

    query_files = list(queries_dir.glob("*.sql"))
    for f in query_files:
        shutil.move(str(f), str(session_queries / f.name))
    print(f"  📂 Moved {len(query_files)} queries → {session_queries}")

    answer_files = list(answers_dir.glob("*.csv"))
    for f in answer_files:
        shutil.move(str(f), str(session_answers / f.name))
    print(f"  📂 Moved {len(answer_files)} answers → {session_answers}")

    if report_dir.exists():
        shutil.copytree(str(report_dir), str(session_report), dirs_exist_ok=True)
        shutil.rmtree(str(report_dir))
        print(f"  📂 Moved reports → {session_report}")

    for d in [queries_dir, answers_dir]:
        if d.exists():
            shutil.rmtree(str(d))

    print(f"  ✓ Session archived → {session_dir}")
    return session_dir
