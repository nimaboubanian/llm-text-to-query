import csv
import json
import math
import re
import shutil
import statistics
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


from text2query.benchmark.similarity import evaluate_query
from text2query.benchmark.pipeline import read_business_question


CSV_FIELDNAMES = [
    "seed", "model", "query_id", "nl_query", "prompt",
    "generated_sql", "real_sql", "status",
    "result_precision", "result_recall", "result_f1",
    "ast_similarity", "error_category",
]


def _write_results_csv(results: list[dict], csv_path: Path) -> None:
    """Write enriched evaluation results to CSV with the fixed column schema."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            row = {field: v if (v := r.get(field)) is not None else "" for field in CSV_FIELDNAMES}
            row["query_id"] = f"{int(r['query_id']):02d}"
            writer.writerow(row)
    print(f"  CSV export -> {csv_path} ({len(results)} rows)")


def _v(val: float | None) -> str:
    if val is None:
        return "—"
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


def _format_per_query(seed_results: list[dict]) -> str:
    """Format a per-query report showing all seeds + aggregated stats."""
    lines = [
        "## Per-Seed Results\n",
        "| Seed | Status | Result F1 | AST Sim |",
        "|---|---|---|---|",
    ]

    for r in seed_results:
        lines.append(
            f"| {r['seed']} | {r['status']} | {_v(r['result_f1'])} "
            f"| {_v(r['ast_similarity'])} |"
        )

    ok_count = sum(1 for r in seed_results if r["status"] == "ok")
    n = len(seed_results)

    lines.append("")
    lines.append("## Aggregated Statistics\n")
    lines.append(f"*Seeds executed successfully: {ok_count} / {n}*\n")

    lines.append("| Metric | Mean | Std | 95% CI |")
    lines.append("|---|---|---|---|")

    for label, metric in [("Result F1", "result_f1"), ("AST Similarity", "ast_similarity")]:
        vals = [r.get(metric) for r in seed_results if r.get(metric) is not None]
        stats = _compute_stats(vals)
        if stats["mean"] is not None:
            ci = f"[{stats['ci_lower']:.4f}, {stats['ci_upper']:.4f}]"
            lines.append(
                f"| {label} | {stats['mean']:.4f} "
                f"| {stats['std']:.4f} | {ci} |"
            )

    return "\n".join(lines) + "\n"


def _format_summary(aggregated: list[dict], num_seeds: int) -> str:
    """Format per-query summary table with mean±std columns."""
    lines = [
        "| Query | Seeds ok | F1 (mean±std) | AST (mean±std) | F1 95% CI |",
        "|---|---|---|---|---|",
    ]

    for q in aggregated:
        qid = f"{q['query_id']:02d}"
        f1 = q["result_f1"]
        ast = q["ast_similarity"]
        ok_count = sum(1 for r in q["per_seed"] if r["status"] == "ok")

        f1_str = f"{f1['mean']:.4f} ± {f1['std']:.4f}" if f1["mean"] is not None else "—"
        ast_str = f"{ast['mean']:.4f} ± {ast['std']:.4f}" if ast["mean"] is not None else "—"
        ci_str = f"[{f1['ci_lower']:.4f}, {f1['ci_upper']:.4f}]" if f1["mean"] is not None else "—"

        lines.append(f"| {qid} | {ok_count}/{num_seeds} | {f1_str} | {ast_str} | {ci_str} |")

    return "\n".join(lines) + "\n"


def generate_reports(
    generated_queries_dir: Path,
    reference_queries_dir: Path,
    generated_answers_dir: Path,
    reference_answers_dir: Path,
    report_dir: Path,
    seeds: list[int] | None = None,
    model: str | None = None,
    selected_ids: list[str] | None = None,
    questions_dir: Path | None = None,
) -> list[dict]:
    """Generate per-query and summary reports, aggregating stats across seeds."""
    seeds = seeds or [1]
    per_query_dir = report_dir / "per_query"
    per_query_dir.mkdir(parents=True, exist_ok=True)

    all_ids = sorted(f.stem for f in reference_queries_dir.glob("*.sql"))
    query_ids = [q for q in all_ids if q in selected_ids] if selected_ids is not None else all_ids

    aggregated = []
    all_flat_results = []
    metrics_to_aggregate = ["result_f1", "ast_similarity"]

    for qid in query_ids:
        seed_results = []
        ref_sql = (reference_queries_dir / f"{qid}.sql").read_text().strip()
        nl_query = read_business_question(questions_dir / f"{qid}.md") if questions_dir else None

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
            sim_result["model"] = model
            sim_result["nl_query"] = nl_query
            prompt_path = seed_queries / f"{qid}.prompt"
            sim_result["prompt"] = prompt_path.read_text() if prompt_path.exists() else None
            gen_sql_path = seed_queries / f"{qid}.sql"
            sim_result["generated_sql"] = gen_sql_path.read_text().strip() if gen_sql_path.exists() else None
            sim_result["real_sql"] = ref_sql
            seed_results.append(sim_result)
        all_flat_results.extend(seed_results)

        # Aggregate statistics across seeds
        query_agg = {"query_id": int(qid)}
        for metric in metrics_to_aggregate:
            vals = [r.get(metric) for r in seed_results if r.get(metric) is not None]
            query_agg[metric] = _compute_stats(vals)

        query_agg["per_seed"] = seed_results
        aggregated.append(query_agg)

        seed_sql_sections = "\n## LLM-Generated SQL by Seed\n\n"
        for seed in seeds:
            seed_sql_path = generated_queries_dir / f"seed_{seed}" / f"{qid}.sql"
            seed_raw_path = generated_queries_dir / f"seed_{seed}" / f"{qid}.raw"
            if seed_sql_path.exists():
                seed_sql_sections += f"### Seed {seed}\n\n```sql\n{seed_sql_path.read_text().strip()}\n```\n\n"
            elif seed_raw_path.exists():
                raw_content = seed_raw_path.read_text().strip()
                if raw_content.startswith("ERROR:"):
                    seed_sql_sections += f"### Seed {seed}\n\n*(generation failed — {raw_content})*\n\n"
                else:
                    snippet = raw_content[:800] + ("\n\n*[truncated]*" if len(raw_content) > 800 else "")
                    seed_sql_sections += f"### Seed {seed}\n\n*(SQL extraction failed — model output:)*\n\n```\n{snippet}\n```\n\n"
            else:
                seed_sql_sections += f"### Seed {seed}\n\n*(not generated)*\n\n"

        meta = f"- **Model:** {model}\n" if model else ""
        report = (
            f"# Query {qid} — Report ({len(seeds)} seed{'s' if len(seeds) > 1 else ''})\n\n"
            f"{meta}"
            f"- **Benchmark:** TPC-H\n\n"
            f"## Reference SQL\n\n```sql\n{ref_sql}\n```\n\n"
            + _format_per_query(seed_results)
            + seed_sql_sections
        )
        (per_query_dir / f"{qid}.md").write_text(report)
        print(f"  [{qid}] evaluated across {len(seeds)} seed{'s' if len(seeds) > 1 else ''}")

    total = len(query_ids)
    exact_matches = sum(
        1 for q in aggregated
        if q["result_f1"]["mean"] is not None and q["result_f1"]["mean"] == 1.0
    )

    model_line = f"| Model | {model} |\n" if model else ""
    summary = (
        f"# Benchmark Summary\n\n"
        f"| Metric | Value |\n"
        f"|---|---|\n"
        f"{model_line}"
        f"| Benchmark | TPC-H |\n"
        f"| Total queries | {total} |\n"
        f"| Seeds per query | {len(seeds)} |\n"
        f"| Total evaluations | {total * len(seeds)} |\n"
        f"| Exact matches (F1 = 1.0 mean) | {exact_matches} |\n\n"
        + _format_summary(aggregated, len(seeds))
    )
    (report_dir / "summary.md").write_text(summary)
    _write_results_csv(all_flat_results, report_dir / "results.csv")

    print(f"  Reports generated -> {report_dir}")
    return all_flat_results


def generate_cross_model_report(
    models: list[str],
    reference_queries_dir: Path,
    report_dir: Path,
    precomputed: dict[str, list[dict]],
    seeds: list[int] | None = None,
    selected_ids: list[str] | None = None,
) -> None:
    """Generate cross-model comparison report and CSV export from already-evaluated results."""
    all_ids = sorted(f.stem for f in reference_queries_dir.glob("*.sql"))
    query_ids = [q for q in all_ids if q in selected_ids] if selected_ids is not None else all_ids
    seeds_list = seeds or [1]

    # Collect all raw results
    all_rows = []
    # {model: {qid: {metric: stats_dict}}}
    model_aggregated = {}

    metrics_to_aggregate = [
        "result_f1", "ast_similarity",
    ]

    for model in models:
        model_aggregated[model] = {}

        # Build (query_id_int, seed) → sim lookup from precomputed results
        precomputed_lookup: dict[tuple, dict] = {
            (r["query_id"], r.get("seed")): r for r in precomputed[model]
        }

        for qid in query_ids:
            seed_results = []

            for seed in seeds_list:
                sim = precomputed_lookup[(int(qid), seed)]
                sim["model"] = model
                seed_results.append(sim)
                all_rows.append(sim)

            agg = {}
            for metric in metrics_to_aggregate:
                vals = [r.get(metric) for r in seed_results if r.get(metric) is not None]
                agg[metric] = _compute_stats(vals)
            ok_count = sum(1 for r in seed_results if r["status"] == "ok")
            n = len(seed_results)
            if n == 1:
                agg["status_summary"] = seed_results[0]["status"]
            else:
                agg["status_summary"] = f"{ok_count}/{n} ok"
            model_aggregated[model][qid] = agg

    # Write CSV
    _write_results_csv(all_rows, report_dir / "results.csv")

    # Write comparison.md
    num_seeds = len(seeds) if seeds else 1

    lines = [
        f"# Cross-Model Comparison ({len(models)} models, {num_seeds} seed{'s' if num_seeds > 1 else ''})\n",
    ]

    header = "| Query | " + " | ".join(m for m in models) + " |"
    sep = "|---|" + "|".join("---" for _ in models) + "|"

    for title, metric, show_status in [("F1", "result_f1", True), ("AST Similarity", "ast_similarity", False)]:
        lines += ["", f"## {title}\n", header, sep]
        for qid in query_ids:
            row = f"| {qid} "
            for model in models:
                agg = model_aggregated[model][qid]
                stats = agg[metric]
                status = agg.get("status_summary", "") if show_status else ""
                prefix = f"{status} · " if status else ""
                if stats["mean"] is None:
                    row += f"| {status} "
                elif num_seeds > 1:
                    row += f"| {prefix}{stats['mean']:.4f} ± {stats['std']:.4f} "
                else:
                    row += f"| {prefix}{stats['mean']:.4f} "
            row += "|"
            lines.append(row)

    comparison_path = report_dir / "comparison.md"
    comparison_path.write_text("\n".join(lines) + "\n")
    print(f"  Comparison report -> {comparison_path}")


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

    _move_contents(queries_dir, session_queries, "queries")
    _move_contents(answers_dir, session_answers, "answers")

    if report_dir.exists():
        shutil.move(str(report_dir), str(session_report))
        print(f"  Moved reports -> {session_report}")

    for d in [queries_dir, answers_dir]:
        if d.exists():
            shutil.rmtree(str(d))

    print(f"  Session archived -> {session_dir}")
    return session_dir


def _move_contents(src_dir: Path, dst_dir: Path, label: str) -> None:
    """Move a directory's subdirectories (model dirs, seed dirs, or nested layouts) to dst."""
    if not src_dir.exists():
        return

    subdirs = sorted(d for d in src_dir.iterdir() if d.is_dir())
    for sd in subdirs:
        shutil.move(str(sd), str(dst_dir))
    if subdirs:
        print(f"  Moved {len(subdirs)} dirs of {label} -> {dst_dir}")


def _redact_db_url(db_url: str) -> str:
    """Strip user:password from a database URL before persisting it in a provenance record."""
    return re.sub(r"//[^@/]*@", "//***:***@", db_url)


def write_session_manifest(
    session_dir: Path,
    *,
    models: list[str],
    seeds: list[int] | None,
    query_ids: list[str] | None,
    scale_factor: int,
    generation_parameters: dict,
    fingerprints: dict[str, str],
    database_url: str,
) -> Path:
    """Write a self-describing provenance manifest for an archived benchmark session."""
    try:
        package_version = version("text2query")
    except PackageNotFoundError:
        package_version = None

    manifest = {
        "timestamp": datetime.now().isoformat(),
        "package_version": package_version,
        "models": models,
        "seeds": seeds,
        "query_ids": query_ids,
        "scale_factor": scale_factor,
        "generation_parameters": generation_parameters,
        "fingerprints": fingerprints,
        "database_url": _redact_db_url(database_url),
    }
    manifest_path = session_dir / "session_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    print(f"  Session manifest -> {manifest_path}")
    return manifest_path

