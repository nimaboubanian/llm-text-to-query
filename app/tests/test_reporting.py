import csv
import re
from pathlib import Path

import pytest

from backend.benchmark.reporting import (
    _compute_stats, generate_reports, format_run_summary,
    METRICS, METRIC_LABELS, _field, format_session_header,
    _aggregate_model_results, _LABEL_WIDTH, _wilson_interval,
    _format_summary, _format_per_query,
)


def test_metrics_constant_has_matching_labels():
    assert METRICS == (
        "execution_accuracy", "result_f1", "ast_similarity", "ast_similarity_normalized",
    )
    assert METRIC_LABELS == {
        "execution_accuracy": "Execution accuracy",
        "result_f1": "Result F1",
        "ast_similarity": "AST similarity",
        "ast_similarity_normalized": "AST sim (norm)",
    }
    assert set(METRICS) == set(METRIC_LABELS)


def test_compute_stats_basic():
    result = _compute_stats([0.85, 0.72, 0.88, 0.65, 0.90])
    assert abs(result["mean"] - 0.8) < 0.001
    assert result["std"] > 0
    assert result["ci_lower"] < result["mean"]
    assert result["ci_upper"] > result["mean"]


def test_compute_stats_single_value_has_no_variance():
    """One sample has no measurable spread — std/CI must be None, not a fabricated 0.0
    that renders as '± 0.0000' and a zero-width CI in the reports."""
    result = _compute_stats([0.85])
    assert result["mean"] == 0.85
    assert result["std"] is None
    assert result["ci_lower"] is None and result["ci_upper"] is None


def test_compute_stats_empty():
    result = _compute_stats([])
    assert result["mean"] is None
    assert result["std"] is None


def test_compute_stats_with_nones():
    result = _compute_stats([0.5, None, 0.7])
    # Should filter out None and compute on [0.5, 0.7]
    assert abs(result["mean"] - 0.6) < 0.001


def _report_dirs(tmp_path):
    """Create the standard generate_reports layout; returns its six paths in order."""
    ref_queries = tmp_path / "ref_queries"
    ref_answers = tmp_path / "ref_answers"
    gen_queries = tmp_path / "gen_queries" / "seed_1"
    gen_answers = tmp_path / "gen_answers" / "seed_1"
    questions = tmp_path / "questions"
    for d in [ref_queries, ref_answers, gen_queries, gen_answers, questions]:
        d.mkdir(parents=True)
    return ref_queries, ref_answers, gen_queries, gen_answers, questions, tmp_path / "report"


def test_results_csv_single_seed(tmp_path):
    """Single-model single-seed runs should emit results.csv with the new columns."""
    ref_queries, ref_answers, gen_queries, gen_answers, questions, report_dir = _report_dirs(tmp_path)

    (ref_queries / "01.sql").write_text("SELECT name FROM customers;")
    (ref_answers / "01.csv").write_text("name\nAlice\n")
    (gen_queries / "01.sql").write_text("SELECT name FROM customers;")
    (gen_queries / "01.prompt").write_text("SCHEMA: customers(name)\nQuestion: list names")
    (gen_answers / "01.csv").write_text("name\nAlice\n")
    (questions / "01.md").write_text('# Business Question:\n  "What are the customer names?"\n')

    generate_reports(
        generated_queries_dir=gen_queries.parent,
        reference_queries_dir=ref_queries,
        generated_answers_dir=gen_answers.parent,
        reference_answers_dir=ref_answers,
        report_dir=report_dir,
        model="m1",
        questions_dir=questions,
    )

    csv_path = report_dir / "results.csv"
    assert csv_path.exists()
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    r = rows[0]
    assert r["seed"] == "1"
    assert r["model"] == "m1"
    assert r["query_id"] == "01"
    assert r["nl_query"] == "What are the customer names?"
    assert r["prompt"] == "SCHEMA: customers(name)\nQuestion: list names"
    assert r["generated_sql"] == "SELECT name FROM customers;"
    assert r["real_sql"] == "SELECT name FROM customers;"


def test_results_csv_includes_timing_columns(tmp_path):
    """A .timing.json sidecar next to a generated query should merge into results.csv."""
    ref_queries, ref_answers, gen_queries, gen_answers, questions, report_dir = _report_dirs(tmp_path)

    (ref_queries / "01.sql").write_text("SELECT name FROM customers;")
    (ref_answers / "01.csv").write_text("name\nAlice\n")
    (gen_queries / "01.sql").write_text("SELECT name FROM customers;")
    (gen_queries / "01.prompt").write_text("SCHEMA: customers(name)\nQuestion: list names")
    (gen_queries / "01.timing.json").write_text(
        '{"prompt_eval_count": 2500, "eval_count": 120, "duration_seconds": 63.0}')
    (gen_answers / "01.csv").write_text("name\nAlice\n")
    (questions / "01.md").write_text('# Business Question:\n  "What are the customer names?"\n')

    generate_reports(
        generated_queries_dir=gen_queries.parent,
        reference_queries_dir=ref_queries,
        generated_answers_dir=gen_answers.parent,
        reference_answers_dir=ref_answers,
        report_dir=report_dir,
        model="m1",
        questions_dir=questions,
    )

    csv_text = (report_dir / "results.csv").read_text()
    header = csv_text.splitlines()[0]
    assert "prompt_eval_count" in header and "generation_seconds" in header
    assert "63.0" in csv_text


def test_results_csv_marks_retried_rows(tmp_path):
    """A <id>.retry.prompt sidecar means the row was retried; its absence means it wasn't."""
    ref_queries, ref_answers, gen_queries, gen_answers, questions, report_dir = _report_dirs(tmp_path)

    for qid in ["01", "02"]:
        (ref_queries / f"{qid}.sql").write_text("SELECT name FROM customers;")
        (ref_answers / f"{qid}.csv").write_text("name\nAlice\n")
        (gen_queries / f"{qid}.sql").write_text("SELECT name FROM customers;")
        (gen_queries / f"{qid}.prompt").write_text("SCHEMA: customers(name)\nQuestion: list names")
        (gen_answers / f"{qid}.csv").write_text("name\nAlice\n")
        (questions / f"{qid}.md").write_text('# Business Question:\n  "What are the customer names?"\n')

    # Only 02 was retried.
    (gen_queries / "02.retry.prompt").write_text("SCHEMA: customers(name)\nQuestion: list names\n\nfix it")

    generate_reports(
        generated_queries_dir=gen_queries.parent,
        reference_queries_dir=ref_queries,
        generated_answers_dir=gen_answers.parent,
        reference_answers_dir=ref_answers,
        report_dir=report_dir,
        model="m1",
        questions_dir=questions,
    )

    with open(report_dir / "results.csv") as f:
        rows = {r["query_id"]: r for r in csv.DictReader(f)}

    assert rows["01"]["retried"] == "False"
    assert rows["02"]["retried"] == "True"

    # 02 eventually matched (execution_accuracy == 1) but only after a retry,
    # so its first attempt was never correct: first_attempt_ex must be 0
    # even though the eventual execution_accuracy is 1.
    assert rows["02"]["execution_accuracy"] == "1"
    assert rows["02"]["first_attempt_ex"] == "0"
    # 01 was never retried: first_attempt_ex must equal execution_accuracy.
    assert rows["01"]["first_attempt_ex"] == rows["01"]["execution_accuracy"]


def test_empty_raw_classified_and_rendered(tmp_path):
    """A zero-byte .raw refines 'missing' to 'empty_response' and the per-query
    report says so instead of '*(not generated)*'."""
    ref_queries, ref_answers, gen_queries, gen_answers, questions, report_dir = _report_dirs(tmp_path)

    (ref_queries / "01.sql").write_text("SELECT name FROM customers;")
    (ref_answers / "01.csv").write_text("name\nAlice\n")
    (gen_queries / "01.raw").write_text("")
    (gen_queries / "01.timing.json").write_text('{"prompt_eval_count": 2400, "eval_count": 1, "duration_seconds": 3.4}')
    (questions / "01.md").write_text('# Business Question:\n  "What are the customer names?"\n')

    results = generate_reports(
        generated_queries_dir=gen_queries.parent,
        reference_queries_dir=ref_queries,
        generated_answers_dir=gen_answers.parent,
        reference_answers_dir=ref_answers,
        report_dir=report_dir,
        model="m1",
        questions_dir=questions,
    )

    assert results[0]["status"] == "empty_response"
    per_query = (report_dir / "per_query" / "01.md").read_text()
    assert "model returned an empty response" in per_query
    assert "eval_count 1" in per_query
    assert "*(not generated)*" not in per_query


def test_summary_omits_variance_columns_at_one_seed(tmp_path):
    """At 1 seed there is no spread to report: summary.md must not print '± 0.0000'
    or a zero-width '[x, x]' CI, which claimed a measurement that was never made."""
    ref_queries, ref_answers, gen_queries, gen_answers, questions, report_dir = _report_dirs(tmp_path)

    (ref_queries / "01.sql").write_text("SELECT name FROM customers;")
    (ref_answers / "01.csv").write_text("name\nAlice\n")
    (gen_queries / "01.sql").write_text("SELECT name FROM customers;")
    (gen_answers / "01.csv").write_text("name\nAlice\n")
    (questions / "01.md").write_text('# Business Question:\n  "Names?"\n')

    generate_reports(
        generated_queries_dir=gen_queries.parent,
        reference_queries_dir=ref_queries,
        generated_answers_dir=gen_answers.parent,
        reference_answers_dir=ref_answers,
        report_dir=report_dir,
        model="m1",
        questions_dir=questions,
    )

    summary = (report_dir / "summary.md").read_text()
    assert "±" not in summary
    assert "| Query | SQL ran | EX | F1 | AST | AST norm |" in summary
    assert "1.0000" in summary  # the real score still shows

    # The headline EX block: a single perfect match -> 1/1 = 1.0000.
    assert "**Execution accuracy** | **1/1 = 1.0000**" in summary
    assert "| Correct on all seeds | 1 / 1 |" in summary
    assert "| First-attempt EX | 1/1 |" in summary

    # The aggregate EX rate may carry a Wilson interval, but no zero-width CI
    # may appear anywhere — that was the original defect.
    for zero_width in ("[1.0000, 1.0000]", "[0.0000, 0.0000]"):
        assert zero_width not in summary

    per_query = (report_dir / "per_query" / "01.md").read_text()
    assert "±" not in per_query
    assert "95% CI" not in per_query


def test_format_per_query_ex_row_uses_wilson_interval_not_negative():
    """Execution accuracy is a binary proportion: its CI must come from the
    Wilson interval, not the normal approximation (mean ± 1.96*std/sqrt(n)),
    which produces a nonsensical negative lower bound at small n (e.g. 1/3
    successes -> [-0.3200, 0.9867])."""
    seed_results = [
        {"seed": 1, "status": "ok", "execution_accuracy": 1, "result_f1": 1.0,
         "ast_similarity": 1.0, "ast_similarity_normalized": 1.0},
        {"seed": 2, "status": "ok", "execution_accuracy": 0, "result_f1": 0.0,
         "ast_similarity": 0.0, "ast_similarity_normalized": 0.0},
        {"seed": 3, "status": "ok", "execution_accuracy": 0, "result_f1": 0.0,
         "ast_similarity": 0.0, "ast_similarity_normalized": 0.0},
    ]
    report = _format_per_query(seed_results)
    ex_line = next(line for line in report.splitlines() if line.startswith("| Execution accuracy"))
    ci_text = ex_line.split("|")[-2].strip()
    lo, hi = (float(x) for x in ci_text.strip("[]").split(","))
    assert 0.0 <= lo <= hi <= 1.0


def test_aggregate_model_results_counts_exact_matches_and_failures():
    rows = [
        {"query_id": 1, "seed": 1, "status": "ok", "execution_accuracy": 1,
         "result_f1": 1.0, "ast_similarity": 0.9},
        {"query_id": 2, "seed": 1, "status": "ok", "execution_accuracy": 0,
         "result_f1": 0.5, "ast_similarity": 0.7},
        {"query_id": 3, "seed": 1, "status": "exec_error", "execution_accuracy": 0,
         "result_f1": 0.0, "ast_similarity": 0.0},
    ]
    agg = _aggregate_model_results(rows)
    assert agg["exact_matches"] == 1
    assert agg["ex_successes"] == 1
    assert agg["ex_total"] == 3
    assert agg["total_queries"] == 3
    assert agg["failures"] == 1
    assert agg["num_seeds"] == 1


def test_aggregate_model_results_exact_match_requires_perfect_mean_across_seeds():
    rows = [
        {"query_id": 1, "seed": 1, "status": "ok", "execution_accuracy": 1,
         "result_f1": 1.0, "ast_similarity": 0.9},
        {"query_id": 1, "seed": 2, "status": "ok", "execution_accuracy": 0,
         "result_f1": 0.8, "ast_similarity": 0.9},
    ]
    agg = _aggregate_model_results(rows)
    assert agg["exact_matches"] == 0  # correct on 1 of 2 seeds, not all
    assert agg["ex_successes"] == 1
    assert agg["total_queries"] == 1
    assert agg["num_seeds"] == 2


def test_format_run_summary_single_model():
    precomputed = {
        "m1": [
            {"query_id": 1, "seed": 1, "status": "ok", "execution_accuracy": 1,
             "result_f1": 1.0, "ast_similarity": 0.9, "ast_similarity_normalized": 0.85},
            {"query_id": 2, "seed": 1, "status": "ok", "execution_accuracy": 0,
             "result_f1": 0.5, "ast_similarity": 0.7, "ast_similarity_normalized": 0.65},
            {"query_id": 3, "seed": 1, "status": "exec_error", "execution_accuracy": 0,
             "result_f1": 0.0, "ast_similarity": 0.0, "ast_similarity_normalized": None},
        ]
    }
    summary = format_run_summary(precomputed, ["m1"], Path("benchmark_results/x"), elapsed=252.0)
    assert "elapsed 4m 12s" in summary
    assert _field("Correct on all seeds", "1 / 3") in summary
    # Regression guard: EX must appear exactly once (fraction+CI), not once from
    # the generic METRICS loop and again from the dedicated EX-rate line.
    assert summary.count("Execution accuracy") == 1
    assert _field("Failures", "1") in summary
    assert _field("Session", "benchmark_results/x") in summary
    assert "password" not in summary
    assert "postgresql" not in summary
    assert _field("AST sim (norm)", "0.7500") in summary


def test_format_run_summary_metric_labels_never_run_into_their_value():
    """Regression: METRIC_LABELS["execution_accuracy"] is 18 chars, one longer than
    the old _LABEL_WIDTH=17, so the label ran straight into its value with no
    separating space ("Execution accuracy0.5000..."). Every metric label must have
    at least one space of separation from its value, regardless of label length."""
    precomputed = {
        "m1": [
            {"query_id": 1, "seed": 1, "status": "ok", "execution_accuracy": 1,
             "result_f1": 1.0, "ast_similarity": 0.9, "ast_similarity_normalized": 0.85},
            {"query_id": 2, "seed": 1, "status": "ok", "execution_accuracy": 0,
             "result_f1": 0.5, "ast_similarity": 0.7, "ast_similarity_normalized": 0.65},
        ]
    }
    summary = format_run_summary(precomputed, ["m1"], Path("benchmark_results/x"), elapsed=5.0)
    # Non-METRICS labels are just as exposed to _LABEL_WIDTH regressions (e.g.
    # "Correct on all seeds" at 20 chars overran the old width of 19) — cover them too.
    other_labels = ["Correct on all seeds", "Failures", "Session"]
    for label in [*METRIC_LABELS.values(), *other_labels]:
        assert re.search(rf"{re.escape(label)}\s+\S", summary), (
            f"label {label!r} is not separated from its value by whitespace"
        )


def test_format_run_summary_multi_model_shows_per_model_row():
    precomputed = {
        "m1": [{"query_id": 1, "seed": 1, "status": "ok", "result_f1": 1.0, "ast_similarity": 0.9}],
        "m2": [{"query_id": 1, "seed": 1, "status": "ok", "result_f1": 0.5, "ast_similarity": 0.7}],
    }
    summary = format_run_summary(precomputed, ["m1", "m2"], Path("benchmark_results/x"), elapsed=5.0)
    assert "m1" in summary
    assert "m2" in summary
    assert "0.5000" in summary
    assert _field("Session", "benchmark_results/x") in summary


def test_field_pads_label_and_wraps_long_values():
    row = _field("Model", "qwen2.5-coder:7b")
    assert row == f"  {'Model':<{_LABEL_WIDTH}}qwen2.5-coder:7b"

    wrapped = _field("Prompt features", "a, " * 40 + "z")
    lines = wrapped.split("\n")
    assert len(lines) > 1
    assert lines[0].startswith(f"  {'Prompt features':<{_LABEL_WIDTH}}")
    # continuation lines line up under the value column, not the label
    assert lines[1].startswith(" " * (2 + _LABEL_WIDTH))


def _assert_field_not_wrapped(text: str, label: str) -> None:
    """Assert the field's rendered row is a single line (no continuation row)."""
    lines = text.splitlines()
    prefix = f"  {label:<{_LABEL_WIDTH}}"
    matches = [i for i, l in enumerate(lines) if l.startswith(prefix)]
    assert matches, f"field {label!r} not found in output"
    i = matches[0]
    indent = " " * (2 + _LABEL_WIDTH)
    wrapped = i + 1 < len(lines) and lines[i + 1].startswith(indent)
    assert not wrapped, f"field {label!r} wrapped to a continuation line: {lines[i]!r} / {lines[i + 1]!r}"


def test_session_header_fields_stay_on_one_line():
    """Regression for the _LABEL_WIDTH=30 bug: widening the label column to
    fit one long label shrank the value column enough to wrap five other
    fields. Render the full composed header (not just _field in isolation)
    and confirm none of them wrap."""
    header = format_session_header(
        scale_factor=1, models=["qwen2.5-coder:7b"], total_available=22,
        query_ids=["01", "07", "16"], num_seeds=1,
        temperature=0.1, max_tokens=2048, num_ctx=4096,
        prompt_flags={"schema_ddl": True, "few_shot": 1, "planning": False},
        database_url="postgresql://user:password@postgres:5432/tpch",
    )
    # "Metrics" is excluded: with 4 metrics (EX added), its joined label list now
    # legitimately exceeds one line — see test_field_pads_label_and_wraps_long_values
    # for continuation-line alignment coverage.
    for label in ("Evaluations", "Prompt features", "LLM params"):
        _assert_field_not_wrapped(header, label)


def test_run_summary_result_f1_field_stays_on_one_line():
    precomputed = {
        "m1": [
            {"query_id": q, "seed": 1, "status": "ok", "result_f1": 1.0,
             "ast_similarity": 0.9, "ast_similarity_normalized": 0.85}
            for q in range(1, 4)
        ]
    }
    summary = format_run_summary(precomputed, ["m1"], Path("benchmark_results/x"), elapsed=5.0)
    _assert_field_not_wrapped(summary, "Result F1")


def test_format_session_header_single_model_filtered_queries():
    header = format_session_header(
        scale_factor=1, models=["qwen2.5-coder:7b"], total_available=22,
        query_ids=["01", "07", "16"], num_seeds=1,
        temperature=0.1, max_tokens=2048, num_ctx=4096,
        prompt_flags={"schema_ddl": True, "few_shot": 1, "planning": False},
        database_url="postgresql://user:password@postgres:5432/tpch",
    )
    assert "TPC-H (scale factor 1)" in header
    assert _field("Model", "qwen2.5-coder:7b") in header
    assert _field("Queries", "3 of 22 (01, 07, 16)") in header
    assert _field("Seeds", "1") in header
    assert _field("Evaluations", "3  (3 queries × 1 seed × 1 model)") in header
    assert _field("Metrics", "Execution accuracy, Result F1, AST similarity, AST sim (norm)") in header
    assert "schema_ddl, few_shot=1" in header
    assert "planning" not in header  # False flags are omitted, not printed as planning=False
    assert "password" not in header
    assert _field("Database", "postgresql://***:***@postgres:5432/tpch") in header


def test_format_session_header_multi_model_all_queries_no_flags():
    header = format_session_header(
        scale_factor=1, models=["m1", "m2"], total_available=22,
        query_ids=None, num_seeds=3,
        temperature=0.1, max_tokens=2048, num_ctx=4096,
        prompt_flags={}, database_url="postgresql://u:p@host/db",
    )
    assert _field("Models", "m1, m2") in header
    assert _field("Queries", "22 of 22 (all)") in header
    assert _field("Evaluations", "132  (22 queries × 3 seeds × 2 models)") in header
    assert _field("Prompt features", "none (baseline)") in header


def test_format_session_header_empty_query_ids_list():
    # Empty list [] (distinct from None) means filter was requested but matched nothing
    header = format_session_header(
        scale_factor=1, models=["m1"], total_available=22,
        query_ids=[], num_seeds=2,
        temperature=0.1, max_tokens=2048, num_ctx=4096,
        prompt_flags={}, database_url="postgresql://u:p@host/db",
    )
    assert _field("Queries", "0 of 22 ()") in header
    # Evaluations must show 0, not fall back to total_available (22)
    assert _field("Evaluations", "0  (0 queries × 2 seeds × 1 model)") in header


def test_wilson_interval_properties():
    """Spec §4: Wilson never leaves [0, 1] even at the degenerate 0%/100% rates
    where the normal approximation collapses to [0, 0] or overshoots 1, it
    brackets the point estimate, it narrows as n grows, and n=0 is undefined."""
    lo, hi = _wilson_interval(0, 10)
    assert lo == 0.0
    assert 0.0 < hi < 1.0

    lo, hi = _wilson_interval(10, 10)
    assert 0.0 < lo < 1.0
    assert hi == 1.0

    lo, hi = _wilson_interval(5, 22)
    assert lo < 5 / 22 < hi

    _, hi_small = _wilson_interval(1, 4)
    _, hi_large = _wilson_interval(25, 100)
    assert (hi_large - 0.25) < (hi_small - 0.25)

    assert _wilson_interval(0, 0) == (None, None)


def test_first_attempt_ex_is_zero_when_retried():
    """A retry only fires when attempt 1 produced no SQL or failed EXPLAIN
    validation, so a retried query's first attempt was never correct (spec §1)."""
    rows = [
        {"query_id": 1, "status": "ok", "execution_accuracy": 1,
         "first_attempt_ex": 1, "retried": False, "result_f1": 1.0},
        {"query_id": 2, "status": "ok", "execution_accuracy": 1,
         "first_attempt_ex": 0, "retried": True, "result_f1": 1.0},
    ]
    agg = _aggregate_model_results(rows)
    assert agg["exact_matches"] == 2
    assert agg["ex_successes"] == 2
    assert agg["ex_total"] == 2
    assert sum(r["first_attempt_ex"] for r in rows) == 1


def test_exact_matches_counted_from_ex_not_f1():
    """Q20's superset scored F1 0.8878 but is not a correct answer."""
    rows = [
        {"query_id": 20, "status": "ok", "execution_accuracy": 0,
         "first_attempt_ex": 0, "retried": False, "result_f1": 0.8878},
    ]
    agg = _aggregate_model_results(rows)
    assert agg["exact_matches"] == 0
    assert agg["ex_successes"] == 0


def test_summary_leads_with_execution_accuracy(tmp_path):
    aggregated = [
        {"query_id": 1,
         "execution_accuracy": {"mean": 1.0, "std": None, "ci_lower": None, "ci_upper": None},
         "result_f1": {"mean": 1.0, "std": None, "ci_lower": None, "ci_upper": None},
         "ast_similarity": {"mean": 0.7, "std": None, "ci_lower": None, "ci_upper": None},
         "ast_similarity_normalized": {"mean": 0.7, "std": None, "ci_lower": None, "ci_upper": None},
         "per_seed": [{"status": "ok", "execution_accuracy": 1}]},
        {"query_id": 20,
         "execution_accuracy": {"mean": 0.0, "std": None, "ci_lower": None, "ci_upper": None},
         "result_f1": {"mean": 0.8878, "std": None, "ci_lower": None, "ci_upper": None},
         "ast_similarity": {"mean": 0.14, "std": None, "ci_lower": None, "ci_upper": None},
         "ast_similarity_normalized": {"mean": 0.3, "std": None, "ci_lower": None, "ci_upper": None},
         "per_seed": [{"status": "ok", "execution_accuracy": 0}]},
    ]
    table = _format_summary(aggregated, num_seeds=1)
    header = table.splitlines()[0]
    assert "EX" in header
    # EX must appear before F1 in the column order
    assert header.index("EX") < header.index("F1")
    # Q20's per-query EX is 0/1 even though its F1 is high
    assert "0/1" in table


@pytest.mark.parametrize("all_fail", [True, False])
def test_summary_headline_reflects_uniform_vs_mixed_failure(tmp_path, all_fail):
    """All-fail-same-way gets a loud headline naming the reason; one success suppresses it."""
    ref_queries, ref_answers, gen_queries, gen_answers, questions, report_dir = _report_dirs(tmp_path)

    if not all_fail:
        (ref_queries / "01.sql").write_text("SELECT name FROM customers;")
        (ref_answers / "01.csv").write_text("name\nAlice\n")
        (gen_queries / "01.sql").write_text("SELECT name FROM customers;")
        (gen_answers / "01.csv").write_text("name\nAlice\n")
        (questions / "01.md").write_text('# Business Question:\n  "Names?"\n')

    failing_qids = ("01", "02") if all_fail else ("02",)
    for qid in failing_qids:
        (ref_queries / f"{qid}.sql").write_text("SELECT name FROM customers;")
        (ref_answers / f"{qid}.csv").write_text("name\nAlice\n")
        (gen_queries / f"{qid}.raw").write_text("")
        (questions / f"{qid}.md").write_text('# Business Question:\n  "Names?"\n')

    generate_reports(
        generated_queries_dir=gen_queries.parent,
        reference_queries_dir=ref_queries,
        generated_answers_dir=gen_answers.parent,
        reference_answers_dir=ref_answers,
        report_dir=report_dir,
        model="m1",
        questions_dir=questions,
    )

    summary = (report_dir / "summary.md").read_text()
    if all_fail:
        assert "⚠ 2/2 generations failed: empty response" in summary
        assert "incompatible with the prompt format" in summary
    else:
        assert "⚠" not in summary
