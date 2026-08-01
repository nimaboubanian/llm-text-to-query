import csv
from pathlib import Path

from text2query.benchmark.reporting import (
    _compute_stats, generate_reports, format_run_summary,
    METRICS, METRIC_LABELS, _field, format_session_header,
    _aggregate_model_results, _LABEL_WIDTH,
)


def test_metrics_constant_has_matching_labels():
    assert METRICS == ("result_f1", "ast_similarity", "ast_similarity_normalized")
    assert METRIC_LABELS == {
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
    assert "95% CI" not in summary
    assert "| Query | SQL ran | F1 | AST | AST norm |" in summary
    assert "1.0000" in summary  # the real score still shows

    per_query = (report_dir / "per_query" / "01.md").read_text()
    assert "±" not in per_query
    assert "95% CI" not in per_query


def test_aggregate_model_results_counts_exact_matches_and_failures():
    rows = [
        {"query_id": 1, "seed": 1, "status": "ok", "result_f1": 1.0, "ast_similarity": 0.9},
        {"query_id": 2, "seed": 1, "status": "ok", "result_f1": 0.5, "ast_similarity": 0.7},
        {"query_id": 3, "seed": 1, "status": "exec_error", "result_f1": 0.0, "ast_similarity": 0.0},
    ]
    agg = _aggregate_model_results(rows)
    assert agg["exact_matches"] == 1
    assert agg["total_queries"] == 3
    assert agg["failures"] == 1
    assert agg["num_seeds"] == 1


def test_aggregate_model_results_exact_match_requires_perfect_mean_across_seeds():
    rows = [
        {"query_id": 1, "seed": 1, "status": "ok", "result_f1": 1.0, "ast_similarity": 0.9},
        {"query_id": 1, "seed": 2, "status": "ok", "result_f1": 0.8, "ast_similarity": 0.9},
    ]
    agg = _aggregate_model_results(rows)
    assert agg["exact_matches"] == 0  # mean F1 across the two seeds is 0.9, not 1.0
    assert agg["total_queries"] == 1
    assert agg["num_seeds"] == 2


def test_format_run_summary_single_model():
    precomputed = {
        "m1": [
            {"query_id": 1, "seed": 1, "status": "ok", "result_f1": 1.0, "ast_similarity": 0.9, "ast_similarity_normalized": 0.85},
            {"query_id": 2, "seed": 1, "status": "ok", "result_f1": 0.5, "ast_similarity": 0.7, "ast_similarity_normalized": 0.65},
            {"query_id": 3, "seed": 1, "status": "exec_error", "result_f1": 0.0, "ast_similarity": 0.0, "ast_similarity_normalized": None},
        ]
    }
    summary = format_run_summary(precomputed, ["m1"], Path("benchmark/results/x"), elapsed=252.0)
    assert "elapsed 4m 12s" in summary
    assert _field("Exact matches", "1 / 3") in summary
    assert _field("Failures", "1") in summary
    assert _field("Session", "benchmark/results/x") in summary
    assert "password" not in summary
    assert "postgresql" not in summary
    # Verify normalized metric is properly formatted with space between label and value
    assert _field("AST sim (norm)", "0.7500") in summary


def test_format_run_summary_multi_model_shows_per_model_row():
    precomputed = {
        "m1": [{"query_id": 1, "seed": 1, "status": "ok", "result_f1": 1.0, "ast_similarity": 0.9}],
        "m2": [{"query_id": 1, "seed": 1, "status": "ok", "result_f1": 0.5, "ast_similarity": 0.7}],
    }
    summary = format_run_summary(precomputed, ["m1", "m2"], Path("benchmark/results/x"), elapsed=5.0)
    assert "m1" in summary
    assert "m2" in summary
    assert "0.5000" in summary
    assert _field("Session", "benchmark/results/x") in summary


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
        database_url="postgresql://user:password@postgres:5432/testdb",
    )
    for label in ("Evaluations", "Metrics", "Prompt features", "LLM params"):
        _assert_field_not_wrapped(header, label)


def test_run_summary_result_f1_field_stays_on_one_line():
    precomputed = {
        "m1": [
            {"query_id": q, "seed": 1, "status": "ok", "result_f1": 1.0,
             "ast_similarity": 0.9, "ast_similarity_normalized": 0.85}
            for q in range(1, 4)
        ]
    }
    summary = format_run_summary(precomputed, ["m1"], Path("benchmark/results/x"), elapsed=5.0)
    _assert_field_not_wrapped(summary, "Result F1")


def test_format_session_header_single_model_filtered_queries():
    header = format_session_header(
        scale_factor=1, models=["qwen2.5-coder:7b"], total_available=22,
        query_ids=["01", "07", "16"], num_seeds=1,
        temperature=0.1, max_tokens=2048, num_ctx=4096,
        prompt_flags={"schema_ddl": True, "few_shot": 1, "planning": False},
        database_url="postgresql://user:password@postgres:5432/testdb",
    )
    assert "TPC-H (scale factor 1)" in header
    assert _field("Model", "qwen2.5-coder:7b") in header
    assert _field("Queries", "3 of 22 (01, 07, 16)") in header
    assert _field("Seeds", "1") in header
    assert _field("Evaluations", "3  (3 queries × 1 seed × 1 model)") in header
    assert _field("Metrics", "Result F1, AST similarity, AST sim (norm)") in header
    assert "schema_ddl, few_shot=1" in header
    assert "planning" not in header  # False flags are omitted, not printed as planning=False
    assert "password" not in header
    assert _field("Database", "postgresql://***:***@postgres:5432/testdb") in header


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
