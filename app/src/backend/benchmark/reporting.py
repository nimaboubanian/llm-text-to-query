"""Stage: score aggregation, report rendering, and session archiving."""
import csv
import json
import math
import re
import shutil
import statistics
import textwrap
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


from backend.benchmark.similarity import evaluate_query
from backend.benchmark.pipeline import read_business_question
from backend.llm.ollama import is_cloud_model


CSV_FIELDNAMES = [
    "seed", "model", "query_id", "nl_query", "prompt",
    "generated_sql", "real_sql", "status",
    "execution_accuracy", "first_attempt_ex",
    "result_precision", "result_recall", "result_f1",
    "ast_similarity", "ast_similarity_normalized", "error_category",
    "prompt_eval_count", "eval_count", "generation_seconds", "retried",
    "cloud",
]

METRICS = ("execution_accuracy", "result_f1", "ast_similarity", "ast_similarity_normalized")
METRIC_LABELS = {
    "execution_accuracy": "Execution accuracy",
    "result_f1": "Result F1",
    "ast_similarity": "AST similarity",
    "ast_similarity_normalized": "AST sim (norm)",
}

_LABEL_WIDTH = 21  # fits "Correct on all seeds" (20 chars) plus >=1 space, like every other label
_VALUE_WIDTH = 41  # independent of _LABEL_WIDTH so widening the label column never re-wraps values


def _field(label: str, value: str) -> str:
    """Render one aligned 'Label   value' row, wrapping long values under the value column."""
    indent = " " * (2 + _LABEL_WIDTH)
    wrapped = textwrap.wrap(value, width=_VALUE_WIDTH, break_long_words=False) or [""]
    rows = [f"  {label:<{_LABEL_WIDTH}}{wrapped[0]}"]
    rows.extend(f"{indent}{cont}" for cont in wrapped[1:])
    return "\n".join(rows)


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return singular if n == 1 else (plural or f"{singular}s")


def format_session_header(
    *,
    scale_factor: int,
    models: list[str],
    total_available: int,
    query_ids: list[str] | None,
    num_seeds: int,
    temperature: float,
    max_tokens: int,
    num_ctx: int,
    prompt_flags: dict,
    database_url: str,
) -> str:
    """Render the session header: what's being benchmarked, and how, printed once up front."""
    rule = "═" * 60
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        rule,
        f"  text2query Benchmark · TPC-H (scale factor {scale_factor})",
        f"  {timestamp}",
        rule,
    ]

    model_label = "Models" if len(models) > 1 else "Model"
    lines.append(_field(model_label, ", ".join(models)))

    if query_ids is None:
        queries_value = f"{total_available} of {total_available} (all)"
    else:
        queries_value = f"{len(query_ids)} of {total_available} ({', '.join(query_ids)})"
    lines.append(_field("Queries", queries_value))

    lines.append(_field("Seeds", str(num_seeds)))

    benchmarked_count = len(query_ids) if query_ids is not None else total_available
    total_evals = benchmarked_count * num_seeds * len(models)
    lines.append(_field(
        "Evaluations",
        f"{total_evals}  ({benchmarked_count} {_plural(benchmarked_count, 'query', 'queries')} "
        f"× {num_seeds} {_plural(num_seeds, 'seed')} × {len(models)} {_plural(len(models), 'model')})",
    ))

    lines.append(_field("Metrics", ", ".join(METRIC_LABELS[m] for m in METRICS)))

    enabled = [(k if isinstance(v, bool) else f"{k}={v}") for k, v in prompt_flags.items() if v]
    lines.append(_field("Prompt features", ", ".join(enabled) if enabled else "none (baseline)"))

    lines.append(_field("LLM params", f"temp={temperature}, max_tokens={max_tokens}, num_ctx={num_ctx}"))

    lines.append(_field("Database", _redact_db_url(database_url)))

    lines.append(rule)
    return "\n".join(lines) + "\n"


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
    print(f"  CSV export ({len(results)} rows)")


def _v(val: float | None) -> str:
    return "—" if val is None else f"{val:.4f}"


def _compute_stats(values: list[float]) -> dict:
    """Mean, std, and 95% CI. std/CI are None below 2 samples — undefined, not zero."""
    values = [v for v in values if v is not None]
    if not values:
        return {"mean": None, "std": None, "ci_lower": None, "ci_upper": None}
    n = len(values)
    mean = statistics.mean(values)
    if n < 2:
        return {"mean": round(mean, 4), "std": None, "ci_lower": None, "ci_upper": None}
    std = statistics.stdev(values)
    ci_margin = 1.96 * std / math.sqrt(n)
    return {
        "mean": round(mean, 4),
        "std": round(std, 4),
        "ci_lower": round(mean - ci_margin, 4),
        "ci_upper": round(mean + ci_margin, 4),
    }


def _wilson_interval(successes: int, n: int) -> tuple[float, float] | tuple[None, None]:
    """95% Wilson score interval for a proportion.

    Used for the binary EX rate instead of the normal approximation, which at
    small n produces degenerate [0, 0] bounds at a 0% rate and can run outside
    [0, 1] — exactly the regime local models sit in.
    """
    if n == 0:
        return None, None
    z = 1.96
    p = successes / n
    denominator = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _format_per_query(seed_results: list[dict]) -> str:
    """Per-query report: every seed, then aggregates. Std/CI omitted at n=1 — see _compute_stats."""
    lines = [
        "## Per-Seed Results\n",
        "| Seed | Status | Result F1 | AST Sim | AST Sim (norm) |",
        "|---|---|---|---|---|",
    ]

    for r in seed_results:
        lines.append(
            f"| {r['seed']} | {r['status']} | {_v(r['result_f1'])} "
            f"| {_v(r['ast_similarity'])} | {_v(r.get('ast_similarity_normalized'))} |"
        )

    ok_count = sum(1 for r in seed_results if r["status"] == "ok")
    n = len(seed_results)

    lines.append("")
    lines.append("## Aggregated Statistics\n")
    lines.append(f"*Seeds executed successfully: {ok_count} / {n}*\n")

    multi = n > 1
    lines.append("| Metric | Mean | Std | 95% CI |" if multi else "| Metric | Value |")
    lines.append("|---|---|---|---|" if multi else "|---|---|")

    for metric in METRICS:
        vals = [r.get(metric) for r in seed_results]
        s = _compute_stats(vals)
        if s["mean"] is None:
            continue
        cells = [METRIC_LABELS[metric], f"{s['mean']:.4f}"]
        if s["std"] is not None:
            # execution_accuracy is a binary proportion: the normal-approximation
            # CI (ci_lower/ci_upper) can go negative at small n, so use Wilson.
            present = [v for v in vals if v is not None]
            lo, hi = (
                _wilson_interval(sum(present), len(present))
                if metric == "execution_accuracy" else (s["ci_lower"], s["ci_upper"])
            )
            cells += [f"{s['std']:.4f}", f"[{lo:.4f}, {hi:.4f}]"]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"


def _format_summary(aggregated: list[dict], num_seeds: int) -> str:
    """Per-query summary, led by EX. Std/CI columns omitted at num_seeds=1."""
    multi = num_seeds > 1
    sfx = " (mean±std)" if multi else ""
    head = ["Query", "SQL ran", "EX", f"F1{sfx}", f"AST{sfx}", f"AST norm{sfx}"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]

    def cell(s: dict) -> str:
        return f"{s['mean']:.4f} ± {s['std']:.4f}" if multi and s["mean"] is not None else _v(s["mean"])

    for q in aggregated:
        per_seed = q["per_seed"]
        ok_count = sum(1 for r in per_seed if r["status"] == "ok")
        ex_count = sum(1 for r in per_seed if r.get("execution_accuracy") == 1)
        row = [
            f"{q['query_id']:02d}",
            f"{ok_count}/{num_seeds}",
            f"{ex_count}/{num_seeds}",
            cell(q["result_f1"]), cell(q["ast_similarity"]),
            cell(q["ast_similarity_normalized"]),
        ]
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines) + "\n"


# A quota abort writes a .raw sentinel with this exact prefix for every query it
# never got to. runner.py imports both constants so the writer and the reader can
# never drift apart.
RATE_LIMITED_MARKER = "ERROR: rate-limited"
RATE_LIMITED_STATUS = "rate_limited"


def _refine_missing_status(status: str, raw_path: Path) -> str:
    """Refine a bare 'missing' into the generation-failure reason recorded in .raw.

    Old sessions have no .raw for empty responses — they keep 'missing'.
    """
    if status != "missing" or not raw_path.exists():
        return status
    raw = raw_path.read_text()
    # Checked before the generic "ERROR:" branch, which this prefix also matches.
    if raw.startswith(RATE_LIMITED_MARKER):
        return RATE_LIMITED_STATUS
    if raw.startswith("ERROR:"):
        return "gen_error"
    return "empty_response" if not raw.strip() else "no_sql_extracted"


# Deliberately excludes RATE_LIMITED_STATUS: this table drives the "model may be
# incompatible with the prompt format" warning, which is false for a quota abort —
# the model never saw those prompts.
_FAILURE_LABELS = {
    "empty_response": "empty response",
    "no_sql_extracted": "no SQL extracted",
    "gen_error": "generation error",
}

_CLOUD_CAVEAT = (
    "> ☁ **Ollama Cloud model.** Generation ran on ollama.com hardware, not this\n"
    "> machine. Durations include network latency and are not comparable to local\n"
    "> timings; accuracy metrics are unaffected.\n\n"
)


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
            sim_result["status"] = _refine_missing_status(
                sim_result["status"], seed_queries / f"{qid}.raw"
            )
            if sim_result["status"] == RATE_LIMITED_STATUS:
                # evaluate_query floors a missing .sql to 0 — right for a model that
                # produced nothing, wrong for work a quota abort never attempted.
                # None drops the row from _compute_stats and from ex_values (both
                # filter it), so it leaves the numerator and the denominator.
                for field in (*METRICS, "result_precision", "result_recall"):
                    sim_result[field] = None
            sim_result["model"] = model
            sim_result["cloud"] = bool(model) and is_cloud_model(model)
            sim_result["nl_query"] = nl_query
            prompt_path = seed_queries / f"{qid}.prompt"
            sim_result["prompt"] = prompt_path.read_text() if prompt_path.exists() else None
            gen_sql_path = seed_queries / f"{qid}.sql"
            sim_result["generated_sql"] = gen_sql_path.read_text().strip() if gen_sql_path.exists() else None
            sim_result["retried"] = (seed_queries / f"{qid}.retry.prompt").exists()
            sim_result["first_attempt_ex"] = (
                0 if sim_result["retried"] else sim_result["execution_accuracy"]
            )
            timing_path = seed_queries / f"{qid}.timing.json"
            if timing_path.exists():
                timing = json.loads(timing_path.read_text())
                sim_result["prompt_eval_count"] = timing.get("prompt_eval_count")
                sim_result["eval_count"] = timing.get("eval_count")
                sim_result["generation_seconds"] = timing.get("duration_seconds")
            sim_result["real_sql"] = ref_sql
            seed_results.append(sim_result)
        all_flat_results.extend(seed_results)

        # Aggregate statistics across seeds
        query_agg = {
            "query_id": int(qid),
            **{m: _compute_stats([r.get(m) for r in seed_results]) for m in METRICS},
            "per_seed": seed_results,
        }
        aggregated.append(query_agg)

        seed_sql_sections = "\n## LLM-Generated SQL by Seed\n\n"
        for seed, r in zip(seeds, seed_results):
            seed_sql_path = generated_queries_dir / f"seed_{seed}" / f"{qid}.sql"
            seed_raw_path = generated_queries_dir / f"seed_{seed}" / f"{qid}.raw"
            if seed_sql_path.exists():
                seed_sql_sections += f"### Seed {seed}\n\n```sql\n{seed_sql_path.read_text().strip()}\n```\n\n"
            elif seed_raw_path.exists():
                raw_content = seed_raw_path.read_text().strip()
                if raw_content.startswith(RATE_LIMITED_MARKER):
                    # The sentinel already carries the server's stated reason — surface it
                    # rather than a generic line, minus the machine-readable prefix.
                    detail = raw_content[len(RATE_LIMITED_MARKER):].lstrip(" —:") or "HTTP 429"
                    seed_sql_sections += (
                        f"### Seed {seed}\n\n*(skipped — rate-limited: {detail})*\n\n"
                    )
                elif raw_content.startswith("ERROR:"):
                    seed_sql_sections += f"### Seed {seed}\n\n*(generation failed — {raw_content})*\n\n"
                elif not raw_content:
                    detail = f" — eval_count {r['eval_count']}" if r.get("eval_count") is not None else ""
                    seed_sql_sections += f"### Seed {seed}\n\n*(model returned an empty response{detail})*\n\n"
                else:
                    snippet = raw_content[:800] + ("\n\n*[truncated]*" if len(raw_content) > 800 else "")
                    seed_sql_sections += f"### Seed {seed}\n\n*(SQL extraction failed — model output:)*\n\n```\n{snippet}\n```\n\n"
            else:
                seed_sql_sections += f"### Seed {seed}\n\n*(not generated)*\n\n"

        cloud = bool(model) and is_cloud_model(model)
        meta = f"- **Model:** {model}{' (Ollama Cloud)' if cloud else ''}\n" if model else ""
        report = (
            f"# Query {qid} — Report ({len(seeds)} {_plural(len(seeds), 'seed')})\n\n"
            f"{_CLOUD_CAVEAT if cloud else ''}"
            f"{meta}"
            f"- **Benchmark:** TPC-H\n\n"
            f"## Reference SQL\n\n```sql\n{ref_sql}\n```\n\n"
            + _format_per_query(seed_results)
            + seed_sql_sections
        )
        (per_query_dir / f"{qid}.md").write_text(report)
        print(f"  [{qid}] evaluated across {len(seeds)} {_plural(len(seeds), 'seed')}")

    total = len(query_ids)
    agg = _aggregate_model_results(all_flat_results)
    ex_successes, ex_total = agg["ex_successes"], agg["ex_total"]
    all_seeds_correct = agg["exact_matches"]
    # `or 0`: rate-limited rows carry None here, and sum() cannot add None.
    first_attempt = sum(r["first_attempt_ex"] or 0 for r in all_flat_results)
    lo, hi = _wilson_interval(ex_successes, ex_total)
    ci_text = f" (95% CI [{lo:.4f}, {hi:.4f}])" if lo is not None else ""
    rate = ex_successes / ex_total if ex_total else 0.0

    statuses = {r["status"] for r in all_flat_results}
    warning = _CLOUD_CAVEAT if (model and is_cloud_model(model)) else ""

    rate_limited = sum(1 for r in all_flat_results if r["status"] == RATE_LIMITED_STATUS)
    if rate_limited:
        warning += (
            f"> ⚠ {rate_limited} of {total * len(seeds)} generations skipped: Ollama Cloud\n"
            "> rate limit (HTTP 429) persisted through a retry, so the run stopped. The scores\n"
            "> below cover only the generations that completed; skipped queries are excluded\n"
            "> from every metric rather than scored 0. Re-run to resume them.\n\n"
        )

    # Exclude rate-limited rows: ex_successes/ex_total already exclude them, and a
    # quota abort mixed in with real failures shouldn't mask an otherwise-uniform
    # failure status.
    non_skipped_statuses = statuses - {RATE_LIMITED_STATUS}
    if ex_successes == 0 and len(non_skipped_statuses) == 1 and (
        label := _FAILURE_LABELS.get(next(iter(non_skipped_statuses)))
    ):
        warning += (
            f"> ⚠ {ex_total}/{ex_total} generations failed: {label} — "
            "model may be incompatible with the prompt format.\n\n"
        )

    model_line = f"| Model | {model} |\n" if model else ""
    summary = (
        f"# Benchmark Summary\n\n{warning}"
        f"| Metric | Value |\n"
        f"|---|---|\n"
        f"{model_line}"
        f"| Benchmark | TPC-H |\n"
        f"| Total queries | {total} |\n"
        f"| Seeds per query | {len(seeds)} |\n"
        f"| Total evaluations | {total * len(seeds)} |\n"
        f"| **Execution accuracy** | **{ex_successes}/{ex_total} = {rate:.4f}**{ci_text} |\n"
        f"| Correct on all seeds | {all_seeds_correct} / {total} |\n"
        f"| First-attempt EX | {first_attempt}/{ex_total} |\n\n"
        + _format_summary(aggregated, len(seeds))
    )
    (report_dir / "summary.md").write_text(summary)
    _write_results_csv(all_flat_results, report_dir / "results.csv")

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

            agg = {m: _compute_stats([r.get(m) for r in seed_results]) for m in METRICS}
            ok_count = sum(1 for r in seed_results if r["status"] == "ok")
            n = len(seed_results)
            agg["status_summary"] = seed_results[0]["status"] if n == 1 else f"{ok_count}/{n} ok"
            model_aggregated[model][qid] = agg

    # Write CSV
    _write_results_csv(all_rows, report_dir / "results.csv")

    # Write comparison.md
    num_seeds = len(seeds_list)

    lines = [
        f"# Cross-Model Comparison ({len(models)} models, {num_seeds} {_plural(num_seeds, 'seed')})\n",
    ]
    cloud_models = [m for m in models if is_cloud_model(m)]
    if cloud_models:
        lines.append(
            "> ☁ **Ran on Ollama Cloud:** " + ", ".join(cloud_models) + ".\n"
            "> Those durations include network latency and ollama.com hardware, and are\n"
            "> not comparable to the local models' timings; accuracy metrics are unaffected.\n"
        )

    header = "| Query | " + " | ".join(models) + " |"
    sep = "|---|" + "|".join("---" for _ in models) + "|"

    for title, metric, show_status in [
        ("Execution Accuracy", "execution_accuracy", True),
        ("F1 (diagnostic)", "result_f1", False),
    ]:
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
                elif stats["std"] is not None:
                    row += f"| {prefix}{stats['mean']:.4f} ± {stats['std']:.4f} "
                else:
                    row += f"| {prefix}{stats['mean']:.4f} "
            row += "|"
            lines.append(row)

    comparison_path = report_dir / "comparison.md"
    comparison_path.write_text("\n".join(lines) + "\n")
    print("  Comparison report generated")


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

    _move_contents(queries_dir, session_queries)
    _move_contents(answers_dir, session_answers)

    if report_dir.exists():
        shutil.move(str(report_dir), str(session_report))

    for d in [queries_dir, answers_dir]:
        if d.exists():
            shutil.rmtree(str(d))

    return session_dir


def _move_contents(src_dir: Path, dst_dir: Path) -> None:
    """Move a directory's subdirectories (model dirs, seed dirs, or nested layouts) to dst."""
    if not src_dir.exists():
        return

    for sd in sorted(d for d in src_dir.iterdir() if d.is_dir()):
        shutil.move(str(sd), str(dst_dir))


def _redact_db_url(db_url: str) -> str:
    """Strip user:password from a database URL before persisting it in a provenance record."""
    return re.sub(r"//[^/]*@", "//***:***@", db_url)


def write_session_manifest(
    session_dir: Path,
    *,
    models: list[str],
    seeds: list[int] | None,
    query_ids: list[str] | None,
    scale_factor: int,
    generation_parameters: dict,
    prompt_flags: dict,
    fingerprints: dict[str, str],
    database_url: str,
    skipped_models: list[str] | None = None,
) -> Path:
    """Write a self-describing provenance manifest for an archived benchmark session.

    `models` is the full configured set; `skipped_models` names any a quota abort cut
    before they ran, which is not derivable from the results on disk.
    """
    try:
        package_version = version("text2query")
    except PackageNotFoundError:
        package_version = None

    manifest = {
        "timestamp": datetime.now().isoformat(),
        "package_version": package_version,
        "models": models,
        "skipped_models": skipped_models or [],
        "seeds": seeds,
        "query_ids": query_ids,
        "scale_factor": scale_factor,
        "generation_parameters": generation_parameters,
        "prompt_flags": prompt_flags,
        "fingerprints": fingerprints,
        "database_url": _redact_db_url(database_url),
    }
    manifest_path = session_dir / "session_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    return manifest_path


def _aggregate_model_results(rows: list[dict]) -> dict:
    """Aggregate one model's flat per-(query, seed) results into summary stats."""
    by_query: dict[int, list[dict]] = {}
    for r in rows:
        by_query.setdefault(r["query_id"], []).append(r)

    metrics = {metric: _compute_stats([r.get(metric) for r in rows]) for metric in METRICS}

    exact_matches = 0
    for qid_rows in by_query.values():
        if any(r["status"] == RATE_LIMITED_STATUS for r in qid_rows):
            continue  # an unattempted seed means "all seeds" was never established
        qid_ex = _compute_stats([r.get("execution_accuracy") for r in qid_rows])
        if qid_ex["mean"] == 1.0:
            exact_matches += 1

    ex_values = [r.get("execution_accuracy") for r in rows if r.get("execution_accuracy") is not None]
    ex_successes = sum(ex_values)
    ex_total = len(ex_values)

    # A rate-limited skip is not a model failure — count it on its own line.
    failures = sum(1 for r in rows if r["status"] not in ("ok", RATE_LIMITED_STATUS))
    skipped = sum(1 for r in rows if r["status"] == RATE_LIMITED_STATUS)

    return {
        "metrics": metrics,
        "exact_matches": exact_matches,
        "ex_successes": ex_successes,
        "ex_total": ex_total,
        "total_queries": len(by_query),
        "failures": failures,
        "skipped": skipped,
        "num_seeds": len(rows) // len(by_query) if by_query else 0,
    }


def format_run_summary(
    precomputed: dict[str, list[dict]],
    models: list[str],
    session_dir: Path,
    elapsed: float,
    skipped_models: list[str] | None = None,
) -> str:
    """Render the closing 'Benchmark Complete' block: aggregate scores, not restated config.

    `models` is the models that actually ran. `skipped_models` names any that a quota
    abort cut before they started, so the summary accounts for the whole configured set.
    """
    rule = "═" * 60
    elapsed_str = f"{int(elapsed) // 60}m {int(elapsed) % 60}s"
    lines = [rule, f"  Benchmark Complete  ·  elapsed {elapsed_str}", rule]

    aggregates = {model: _aggregate_model_results(precomputed[model]) for model in models}

    if len(models) == 1:
        agg = aggregates[models[0]]
        lo, hi = _wilson_interval(agg["ex_successes"], agg["ex_total"])
        ci_text = f"   95% CI [{lo:.4f}, {hi:.4f}]" if lo is not None else ""
        lines.append(_field(
            "Execution accuracy",
            f"{agg['ex_successes']} / {agg['ex_total']}{ci_text}",
        ))
        # execution_accuracy already reported above as a fraction+CI; the loop over
        # the remaining METRICS covers the diagnostic mean-score metrics only.
        diagnostic_metrics = [m for m in METRICS if m != "execution_accuracy"]
        for i, metric in enumerate(diagnostic_metrics):
            stats = agg["metrics"][metric]
            value = _v(stats["mean"])
            if i == 0:
                value += (
                    f"   (mean over {agg['total_queries']} "
                    f"{_plural(agg['total_queries'], 'query', 'queries')} × "
                    f"{agg['num_seeds']} {_plural(agg['num_seeds'], 'seed')})"
                )
            lines.append(_field(METRIC_LABELS[metric], value))
        lines.append(_field("Correct on all seeds", f"{agg['exact_matches']} / {agg['total_queries']}"))
        lines.append(_field("Failures", str(agg["failures"])))
        if agg["skipped"]:
            lines.append(_field("Skipped (rate-limited)", str(agg["skipped"])))
    else:
        name_width = max(len("Model"), max(len(m) for m in models))
        lines.append(
            f"  {'Model':<{name_width}}   {'EX':>9}   {'F1':>7}   {'AST sim':>8}   {'All seeds':>9}   {'Fail':>4}"
        )
        for model in models:
            agg = aggregates[model]
            ex_str = _v(agg["metrics"]["execution_accuracy"]["mean"])
            f1_str = _v(agg["metrics"]["result_f1"]["mean"])
            ast_str = _v(agg["metrics"]["ast_similarity"]["mean"])
            seeds_str = f"{agg['exact_matches']} / {agg['total_queries']}"
            lines.append(
                f"  {model:<{name_width}}   {ex_str:>9}   {f1_str:>7}   {ast_str:>8}   {seeds_str:>9}   {agg['failures']:>4}"
            )

        skips = [f"{m}: {aggregates[m]['skipped']}" for m in models if aggregates[m]["skipped"]]
        if skips:
            lines.append("")
            lines.append(_field("Skipped (rate-limited)", ", ".join(skips)))

    lines.append("")
    if skipped_models:
        lines.append(_field("Not run (rate-limited)", ", ".join(skipped_models)))
    lines.append(_field("Session", str(session_dir)))
    lines.append(rule)
    return "\n".join(lines) + "\n"

