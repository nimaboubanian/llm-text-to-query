import csv
import math
import shutil
import statistics
from datetime import datetime
from pathlib import Path


from text2query.benchmark.similarity import evaluate_query


def model_slug(model_name: str) -> str:
    """Convert model name to a filesystem-safe slug."""
    return model_name.replace(":", "_").replace("/", "_")


def _v(val: float | bool | None) -> str:
    if val is None:
        return "—"
    if isinstance(val, bool):
        return "Yes" if val else "No"
    return f"{val:.4f}"


def _compute_stats(values: list[float]) -> dict:
    """Compute mean, std, and 95% confidence interval for a list of values."""
    values = [v for v in values if v is not None]
    if not values:
        return {"mean": None, "std": None, "ci_lower": None, "ci_upper": None}
    n = len(values)
    mean = statistics.mean(values)
    std = statistics.stdev(values) if n > 1 else 0.0
    ci_margin = 1.96 * std / math.sqrt(n) if n > 1 else 0.0
    return {
        "mean": round(mean, 4),
        "std": round(std, 4),
        "ci_lower": round(mean - ci_margin, 4),
        "ci_upper": round(mean + ci_margin, 4),
    }


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
        f"| BLEU | {_v(result.get('bleu'))} |",
        f"| Token Jaccard | {_v(result.get('token_jaccard'))} |",
    ]

    if result.get("error_category"):
        lines.append(f"| Error Category | {result['error_category']} |")

    clause = result.get("clause_scores")
    if clause:
        lines.append("")
        lines.append("### Clause Breakdown\n")
        lines.append("| Clause | Match |")
        lines.append("|---|---|")
        for name, score in clause.items():
            lines.append(f"| {name} | {_v(score)} |")

    return "\n".join(lines) + "\n"


def _format_per_query_multiseed(seed_results: list[dict]) -> str:
    """Format per-query report for multi-seed runs showing all seeds + aggregated stats."""
    lines = [
        "## Per-Seed Results\n",
        "| Seed | Status | Result F1 | AST Sim | BLEU | Jaccard | Composite |",
        "|---|---|---|---|---|---|---|",
    ]

    for r in seed_results:
        lines.append(
            f"| {r['seed']} | {r['status']} | {_v(r['result_f1'])} "
            f"| {_v(r['ast_similarity'])} | {_v(r.get('bleu'))} "
            f"| {_v(r.get('token_jaccard'))} | {_v(r.get('composite_score'))} |"
        )

    lines.append("")
    lines.append("## Aggregated Statistics\n")

    metrics = ["result_f1", "ast_similarity", "bleu", "token_jaccard", "composite_score"]
    metric_labels = {
        "result_f1": "Result F1",
        "ast_similarity": "AST Similarity",
        "bleu": "BLEU",
        "token_jaccard": "Token Jaccard",
        "composite_score": "Composite Score",
    }

    lines.append("| Metric | Mean | Std | 95% CI |")
    lines.append("|---|---|---|---|")

    for metric in metrics:
        vals = [r.get(metric) for r in seed_results if r.get(metric) is not None]
        stats = _compute_stats(vals)
        if stats["mean"] is not None:
            ci = f"[{stats['ci_lower']:.4f}, {stats['ci_upper']:.4f}]"
            lines.append(
                f"| {metric_labels[metric]} | {stats['mean']:.4f} "
                f"| {stats['std']:.4f} | {ci} |"
            )

    return "\n".join(lines) + "\n"


def _format_summary_similarity(all_results: list[dict]) -> str:
    exact_count = sum(1 for r in all_results if r.get("exact_match") is True)
    total = len(all_results)

    f1_vals = [r["result_f1"] if r["result_f1"] is not None else 0.0 for r in all_results]
    ast_vals = [r["ast_similarity"] if r["ast_similarity"] is not None else 0.0 for r in all_results]
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

    comp_vals = [r["composite_score"] if r.get("composite_score") is not None else 0.0 for r in all_results]
    avg_comp = sum(comp_vals) / len(comp_vals) if comp_vals else 0.0
    lines.append(f"- **Average Composite Score:** {avg_comp:.4f}")

    if error_counts:
        lines.append(f"- **Execution errors:** {len(error_results)}")
        for cat, count in sorted(error_counts.items()):
            lines.append(f"  - {cat}: {count}")

    lines += [
        "",
        "| Query | Status | Result F1 | AST Sim | BLEU | Jaccard | Composite |",
        "|---|---|---|---|---|---|---|",
    ]

    for r in all_results:
        qid = f"{r['query_id']:02d}"
        lines.append(
            f"| {qid} | {r['status']} | {_v(r['result_f1'])} "
            f"| {_v(r['ast_similarity'])} | {_v(r.get('bleu'))} "
            f"| {_v(r.get('token_jaccard'))} | {_v(r.get('composite_score'))} |"
        )

    return "\n".join(lines) + "\n"


def _format_summary_multiseed(aggregated: list[dict], num_seeds: int) -> str:
    """Format summary report for multi-seed runs with mean±std columns."""
    total = len(aggregated)

    # Global aggregates across all queries
    f1_means = [q["result_f1"]["mean"] if q["result_f1"]["mean"] is not None else 0.0 for q in aggregated]
    ast_means = [q["ast_similarity"]["mean"] if q["ast_similarity"]["mean"] is not None else 0.0 for q in aggregated]
    comp_means = [q["composite_score"]["mean"] if q["composite_score"]["mean"] is not None else 0.0 for q in aggregated]

    global_f1 = _compute_stats(f1_means)
    global_ast = _compute_stats(ast_means)
    global_comp = _compute_stats(comp_means)

    lines = [
        f"## Similarity Metrics ({num_seeds} seeds)\n",
        f"- **Queries evaluated:** {total}",
    ]

    if global_f1["mean"] is not None:
        lines.append(f"- **Average Result F1:** {global_f1['mean']:.4f} ± {global_f1['std']:.4f}")
    if global_ast["mean"] is not None:
        lines.append(f"- **Average AST Similarity:** {global_ast['mean']:.4f} ± {global_ast['std']:.4f}")
    if global_comp["mean"] is not None:
        lines.append(f"- **Average Composite Score:** {global_comp['mean']:.4f} ± {global_comp['std']:.4f}")

    lines += [
        "",
        "| Query | F1 (mean±std) | AST (mean±std) | Composite (mean±std) | F1 95% CI |",
        "|---|---|---|---|---|",
    ]

    for q in aggregated:
        qid = f"{q['query_id']:02d}"
        f1 = q["result_f1"]
        ast = q["ast_similarity"]
        comp = q["composite_score"]

        f1_str = f"{f1['mean']:.4f} ± {f1['std']:.4f}" if f1["mean"] is not None else "—"
        ast_str = f"{ast['mean']:.4f} ± {ast['std']:.4f}" if ast["mean"] is not None else "—"
        comp_str = f"{comp['mean']:.4f} ± {comp['std']:.4f}" if comp["mean"] is not None else "—"
        ci_str = f"[{f1['ci_lower']:.4f}, {f1['ci_upper']:.4f}]" if f1["mean"] is not None else "—"

        lines.append(f"| {qid} | {f1_str} | {ast_str} | {comp_str} | {ci_str} |")

    return "\n".join(lines) + "\n"


def generate_reports(
    generated_queries_dir: Path,
    reference_queries_dir: Path,
    generated_answers_dir: Path,
    reference_answers_dir: Path,
    report_dir: Path,
    seeds: list[int] | None = None,
) -> Path:
    if seeds and len(seeds) > 1:
        return _generate_multiseed_reports(
            generated_queries_dir, reference_queries_dir,
            generated_answers_dir, reference_answers_dir,
            report_dir, seeds,
        )
    else:
        return _generate_single_reports(
            generated_queries_dir, reference_queries_dir,
            generated_answers_dir, reference_answers_dir,
            report_dir,
        )


def _generate_single_reports(
    generated_queries_dir: Path,
    reference_queries_dir: Path,
    generated_answers_dir: Path,
    reference_answers_dir: Path,
    report_dir: Path,
) -> Path:
    """Original single-seed report generation (backward compatible)."""
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


def _generate_multiseed_reports(
    generated_queries_dir: Path,
    reference_queries_dir: Path,
    generated_answers_dir: Path,
    reference_answers_dir: Path,
    report_dir: Path,
    seeds: list[int],
) -> Path:
    """Generate reports aggregating multiple seed runs with statistical analysis."""
    per_query_dir = report_dir / "per_query"
    per_query_dir.mkdir(parents=True, exist_ok=True)

    query_ids = sorted(
        f.stem for f in reference_queries_dir.glob("*.sql")
    )

    aggregated = []
    metrics_to_aggregate = [
        "result_f1", "result_precision", "result_recall",
        "ast_similarity", "composite_score", "bleu", "token_jaccard",
    ]

    for qid in query_ids:
        seed_results = []

        for seed in seeds:
            seed_queries = generated_queries_dir / f"seed_{seed}"
            seed_answers = generated_answers_dir / f"seed_{seed}"

            sim_result = evaluate_query(
                query_id=int(qid),
                gt_csv=reference_answers_dir / f"{qid}.csv",
                llm_csv=seed_answers / f"{qid}.csv",
                gt_sql=reference_queries_dir / f"{qid}.sql",
                llm_sql=seed_queries / f"{qid}.sql",
            )
            sim_result["seed"] = seed
            seed_results.append(sim_result)

        # Aggregate statistics across seeds
        query_agg = {"query_id": int(qid)}
        for metric in metrics_to_aggregate:
            vals = [r.get(metric) for r in seed_results if r.get(metric) is not None]
            query_agg[metric] = _compute_stats(vals)

        query_agg["per_seed"] = seed_results
        aggregated.append(query_agg)

        # Per-query report with all seeds
        report = (
            f"# Query {qid} — Multi-Seed Report ({len(seeds)} seeds)\n\n"
            + _format_per_query_multiseed(seed_results)
        )
        (per_query_dir / f"{qid}.md").write_text(report)
        print(f"  [{qid}] evaluated across {len(seeds)} seeds")

    total = len(query_ids)

    summary = (
        f"# Benchmark Summary (Multi-Seed)\n\n"
        f"| Metric | Value |\n"
        f"|---|---|\n"
        f"| Total queries | {total} |\n"
        f"| Seeds per query | {len(seeds)} |\n"
        f"| Total evaluations | {total * len(seeds)} |\n\n"
        + _format_summary_multiseed(aggregated, len(seeds))
    )
    (report_dir / "summary.md").write_text(summary)

    print(f"  Reports generated -> {report_dir}")
    return report_dir


def generate_cross_model_report(
    models: list[str],
    reference_queries_dir: Path,
    reference_answers_dir: Path,
    generated_queries_base: Path,
    generated_answers_base: Path,
    report_dir: Path,
    seeds: list[int] | None = None,
) -> Path:
    """Generate cross-model comparison report and CSV export."""
    query_ids = sorted(f.stem for f in reference_queries_dir.glob("*.sql"))
    seeds_list = seeds or [None]
    multi_seed = seeds is not None and len(seeds) > 1

    # Collect all raw results
    all_rows = []
    # {model: {qid: {metric: stats_dict}}}
    model_aggregated = {}

    metrics_to_aggregate = [
        "result_f1", "ast_similarity", "composite_score", "bleu", "token_jaccard",
    ]

    for model in models:
        slug = model_slug(model)
        model_queries = generated_queries_base / slug
        model_answers = generated_answers_base / slug
        model_aggregated[model] = {}

        for qid in query_ids:
            seed_results = []

            for seed in seeds_list:
                if multi_seed:
                    q_dir = model_queries / f"seed_{seed}"
                    a_dir = model_answers / f"seed_{seed}"
                else:
                    q_dir = model_queries
                    a_dir = model_answers

                sim = evaluate_query(
                    query_id=int(qid),
                    gt_csv=reference_answers_dir / f"{qid}.csv",
                    llm_csv=a_dir / f"{qid}.csv",
                    gt_sql=reference_queries_dir / f"{qid}.sql",
                    llm_sql=q_dir / f"{qid}.sql",
                )
                sim["seed"] = seed
                seed_results.append(sim)

                all_rows.append({
                    "model": model,
                    "query_id": qid,
                    "seed": seed if seed is not None else "",
                    "status": sim["status"],
                    "result_f1": sim.get("result_f1", ""),
                    "result_precision": sim.get("result_precision", ""),
                    "result_recall": sim.get("result_recall", ""),
                    "ast_similarity": sim.get("ast_similarity", ""),
                    "bleu": sim.get("bleu", ""),
                    "token_jaccard": sim.get("token_jaccard", ""),
                    "composite_score": sim.get("composite_score", ""),
                    "exact_match": sim.get("exact_match", ""),
                    "error_category": sim.get("error_category", ""),
                })

            agg = {}
            for metric in metrics_to_aggregate:
                vals = [r.get(metric) for r in seed_results if r.get(metric) is not None]
                agg[metric] = _compute_stats(vals)
            model_aggregated[model][qid] = agg

    # Write CSV
    csv_path = report_dir / "results.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "model", "query_id", "seed", "status",
        "result_f1", "result_precision", "result_recall",
        "ast_similarity", "bleu", "token_jaccard", "composite_score",
        "exact_match", "error_category",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"  CSV export -> {csv_path} ({len(all_rows)} rows)")

    # Write comparison.md
    num_seeds = len(seeds) if seeds else 1

    lines = [
        f"# Cross-Model Comparison ({len(models)} models, {num_seeds} seed{'s' if num_seeds > 1 else ''})\n",
        "## Model Summary\n",
        "| Model | Avg F1 | Avg AST Sim | Avg Composite |",
        "|---|---|---|---|",
    ]

    def _stat_str(s):
        if s["mean"] is None:
            return "—"
        return f"{s['mean']:.4f} ± {s['std']:.4f}" if num_seeds > 1 else f"{s['mean']:.4f}"

    for model in models:
        f1_means = [
            model_aggregated[model][qid]["result_f1"]["mean"] if model_aggregated[model][qid]["result_f1"]["mean"] is not None else 0.0
            for qid in query_ids
        ]
        ast_means = [
            model_aggregated[model][qid]["ast_similarity"]["mean"] if model_aggregated[model][qid]["ast_similarity"]["mean"] is not None else 0.0
            for qid in query_ids
        ]
        comp_means = [
            model_aggregated[model][qid]["composite_score"]["mean"] if model_aggregated[model][qid]["composite_score"]["mean"] is not None else 0.0
            for qid in query_ids
        ]
        lines.append(
            f"| {model} | {_stat_str(_compute_stats(f1_means))} "
            f"| {_stat_str(_compute_stats(ast_means))} "
            f"| {_stat_str(_compute_stats(comp_means))} |"
        )

    # Per-query comparison table (F1)
    lines += [
        "",
        "## Per-Query F1 Comparison\n",
    ]
    header = "| Query | " + " | ".join(m for m in models) + " |"
    sep = "|---|" + "|".join("---" for _ in models) + "|"
    lines += [header, sep]

    for qid in query_ids:
        row = f"| {qid} "
        for model in models:
            f1 = model_aggregated[model][qid]["result_f1"]
            if f1["mean"] is None:
                row += "| — "
            elif num_seeds > 1:
                row += f"| {f1['mean']:.4f} ± {f1['std']:.4f} "
            else:
                row += f"| {f1['mean']:.4f} "
        row += "|"
        lines.append(row)

    comparison_path = report_dir / "comparison.md"
    comparison_path.write_text("\n".join(lines) + "\n")
    print(f"  Comparison report -> {comparison_path}")

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

    # Move queries — handle both flat files and seed subdirectories
    _move_contents(queries_dir, session_queries, "queries")

    # Move answers — handle both flat files and seed subdirectories
    _move_contents(answers_dir, session_answers, "answers")

    if report_dir.exists():
        shutil.copytree(str(report_dir), str(session_report), dirs_exist_ok=True)
        shutil.rmtree(str(report_dir))
        print(f"  Moved reports -> {session_report}")

    for d in [queries_dir, answers_dir]:
        if d.exists():
            shutil.rmtree(str(d))

    print(f"  Session archived -> {session_dir}")
    return session_dir


def _move_contents(src_dir: Path, dst_dir: Path, label: str) -> None:
    """Move files and subdirectories from src to dst."""
    if not src_dir.exists():
        return

    # Move subdirectories (model dirs, seed dirs, or any nested structure)
    subdirs = sorted(d for d in src_dir.iterdir() if d.is_dir())
    if subdirs:
        for sd in subdirs:
            target = dst_dir / sd.name
            shutil.copytree(str(sd), str(target), dirs_exist_ok=True)
        print(f"  Moved {len(subdirs)} dirs of {label} -> {dst_dir}")

    # Move flat files (single-seed, single-model / backward compat)
    files = list(src_dir.glob("*.sql")) + list(src_dir.glob("*.csv"))
    for f in files:
        shutil.move(str(f), str(dst_dir / f.name))
    if files:
        print(f"  Moved {len(files)} {label} -> {dst_dir}")

