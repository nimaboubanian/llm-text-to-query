import shutil
from datetime import datetime
from pathlib import Path

from text2query.benchmark.similarity import evaluate_query


def _v(val: float | bool | None) -> str:
    if val is None:
        return "—"
    if isinstance(val, bool):
        return "Yes" if val else "No"
    return f"{val:.4f}"


def _format_per_query_similarity(result: dict) -> str:
    lines = [
        "## Similarity Analysis\n",
        "| Metric | Value |",
        "|---|---|",
        f"| Result F1 | {_v(result['result_f1'])} |",
        f"| Precision | {_v(result['result_precision'])} |",
        f"| Recall | {_v(result['result_recall'])} |",
        f"| Exact Match | {_v(result['exact_match'])} |",
        f"| AST Similarity | {_v(result['ast_similarity'])} |",
        f"| Composite Score | {_v(result.get('composite_score'))} |",
    ]

    if result.get("error_category"):
        lines.append(f"| Error Category | {result['error_category']} |")

    return "\n".join(lines) + "\n"


def _format_summary_similarity(all_results: list[dict]) -> str:
    exact_count = sum(1 for r in all_results if r.get("exact_match") is True)
    total = len(all_results)

    f1_vals = [r["result_f1"] for r in all_results if r["result_f1"] is not None]
    ast_vals = [r["ast_similarity"] for r in all_results if r["ast_similarity"] is not None]
    avg_f1 = sum(f1_vals) / len(f1_vals) if f1_vals else 0.0
    avg_ast = sum(ast_vals) / len(ast_vals) if ast_vals else 0.0

    error_results = [r for r in all_results if r.get("error_category")]
    error_counts = {}
    for r in error_results:
        cat = r["error_category"]
        error_counts[cat] = error_counts.get(cat, 0) + 1

    lines = [
        "## Similarity Metrics\n",
        f"- **Exact matches:** {exact_count} / {total}",
        f"- **Average Result F1:** {avg_f1:.4f}",
        f"- **Average AST Similarity:** {avg_ast:.4f}",
    ]

    comp_vals = [r["composite_score"] for r in all_results if r.get("composite_score") is not None]
    avg_comp = sum(comp_vals) / len(comp_vals) if comp_vals else 0.0
    lines.append(f"- **Average Composite Score:** {avg_comp:.4f}")

    if error_counts:
        lines.append(f"- **Execution errors:** {len(error_results)}")
        for cat, count in sorted(error_counts.items()):
            lines.append(f"  - {cat}: {count}")

    lines += [
        "",
        "| Query | Status | Result F1 | Exact Match | AST Similarity | Composite |",
        "|---|---|---|---|---|---|",
    ]

    for r in all_results:
        qid = f"{r['query_id']:02d}"
        lines.append(
            f"| {qid} | {r['status']} | {_v(r['result_f1'])} | {_v(r['exact_match'])} "
            f"| {_v(r['ast_similarity'])} | {_v(r.get('composite_score'))} |"
        )

    return "\n".join(lines) + "\n"


def generate_reports(
    generated_queries_dir: Path,
    reference_queries_dir: Path,
    generated_answers_dir: Path,
    reference_answers_dir: Path,
    report_dir: Path,
) -> Path:
    per_query_dir = report_dir / "per_query"
    per_query_dir.mkdir(parents=True, exist_ok=True)

    query_ids = sorted(
        f.stem for f in reference_queries_dir.glob("*.sql")
    )

    executed = 0
    errors = 0
    all_results = []

    for qid in query_ids:
        has_generated = (generated_queries_dir / f"{qid}.sql").exists()
        has_answer = (generated_answers_dir / f"{qid}.csv").exists()

        is_error = False
        if has_answer:
            first_line = (generated_answers_dir / f"{qid}.csv").read_text().split("\n", 1)[0]
            is_error = first_line.strip() == "ERROR"

        status = "error" if is_error else ("executed" if has_answer else "not generated")

        if is_error:
            errors += 1
        elif has_answer:
            executed += 1

        sim_result = evaluate_query(
            query_id=int(qid),
            gt_csv=reference_answers_dir / f"{qid}.csv",
            llm_csv=generated_answers_dir / f"{qid}.csv",
            gt_sql=reference_queries_dir / f"{qid}.sql",
            llm_sql=generated_queries_dir / f"{qid}.sql",
        )
        all_results.append(sim_result)

        report = (
            f"# Query {qid} — Report\n\n"
            f"- **Status:** {status}\n"
            f"- **LLM query generated:** {'yes' if has_generated else 'no'}\n"
            f"- **LLM answer produced:** {'yes' if has_answer and not is_error else 'no'}\n\n"
            + _format_per_query_similarity(sim_result)
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
        f"| Not generated | {not_generated} |\n\n"
        + _format_summary_similarity(all_results)
    )
    (report_dir / "summary.md").write_text(summary)

    print(f"  Reports generated -> {report_dir}")
    return report_dir


def archive_session(
    queries_dir: Path,
    answers_dir: Path,
    report_dir: Path,
    results_base: Path,
) -> Path:
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
    print(f"  Moved {len(query_files)} queries -> {session_queries}")

    answer_files = list(answers_dir.glob("*.csv"))
    for f in answer_files:
        shutil.move(str(f), str(session_answers / f.name))
    print(f"  Moved {len(answer_files)} answers -> {session_answers}")

    if report_dir.exists():
        shutil.copytree(str(report_dir), str(session_report), dirs_exist_ok=True)
        shutil.rmtree(str(report_dir))
        print(f"  Moved reports -> {session_report}")

    for d in [queries_dir, answers_dir]:
        if d.exists():
            shutil.rmtree(str(d))

    print(f"  Session archived -> {session_dir}")
    return session_dir
