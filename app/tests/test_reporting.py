import csv
from pathlib import Path

from text2query.benchmark.reporting import (
    _compute_stats, generate_reports, format_run_summary,
    METRICS, METRIC_LABELS, _field, format_session_header,
)


def test_metrics_constant_has_matching_labels():
    assert METRICS == ("result_f1", "ast_similarity")
    assert METRIC_LABELS == {"result_f1": "Result F1", "ast_similarity": "AST similarity"}
    assert set(METRICS) == set(METRIC_LABELS)


def test_compute_stats_basic():
    result = _compute_stats([0.85, 0.72, 0.88, 0.65, 0.90])
    assert abs(result["mean"] - 0.8) < 0.001
    assert result["std"] > 0
    assert result["ci_lower"] < result["mean"]
    assert result["ci_upper"] > result["mean"]


def test_compute_stats_single_value():
    result = _compute_stats([0.85])
    assert result["mean"] == 0.85
    assert result["std"] == 0.0
    assert result["ci_lower"] == result["ci_upper"] == 0.85


def test_compute_stats_empty():
    result = _compute_stats([])
    assert result["mean"] is None
    assert result["std"] is None


def test_compute_stats_with_nones():
    result = _compute_stats([0.5, None, 0.7])
    # Should filter out None and compute on [0.5, 0.7]
    assert abs(result["mean"] - 0.6) < 0.001


def test_results_csv_single_seed(tmp_path):
    """Single-model single-seed runs should emit results.csv with the new columns."""
    ref_queries = tmp_path / "ref_queries"
    ref_answers = tmp_path / "ref_answers"
    gen_queries = tmp_path / "gen_queries" / "seed_1"
    gen_answers = tmp_path / "gen_answers" / "seed_1"
    questions = tmp_path / "questions"
    report_dir = tmp_path / "report"
    for d in [ref_queries, ref_answers, gen_queries, gen_answers, questions]:
        d.mkdir(parents=True)

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


def test_format_run_summary_single_model_all_queries():
    summary = format_run_summary(
        total_questions=22, total_ground_truth=22, query_ids=None,
        models=["m1"], num_seeds=1, session_dir=Path("benchmark/results/x"),
        database_url="postgresql://u:p@host/db",
        prompt_flags={},
    )
    assert "Queries benchmarked: 22 / 22 (all)" in summary
    assert "Model:               m1" in summary
    assert "Total evaluations:   22 (22 queries × 1 seeds × 1 model)" in summary
    assert "Prompt features:     none (baseline)" in summary


def test_format_run_summary_multi_model_filtered_queries():
    summary = format_run_summary(
        total_questions=22, total_ground_truth=22, query_ids=["01", "02"],
        models=["m1", "m2"], num_seeds=3, session_dir=Path("benchmark/results/x"),
        database_url="postgresql://u:p@host/db",
        prompt_flags={"schema_ddl": True, "few_shot": 2},
    )
    assert "Queries benchmarked: 2 / 22 (01, 02)" in summary
    assert "Models:              m1, m2" in summary
    assert "Total evaluations:   6 (2 queries × 3 seeds × 2 models)" in summary
    assert "Prompt features:     schema_ddl, few_shot=2" in summary


def test_field_pads_label_and_wraps_long_values():
    row = _field("Model", "qwen2.5-coder:7b")
    assert row == "  Model             qwen2.5-coder:7b"

    wrapped = _field("Prompt features", "a, " * 40 + "z")
    lines = wrapped.split("\n")
    assert len(lines) > 1
    assert lines[0].startswith("  Prompt features  ")
    # continuation lines line up under the value column, not the label
    assert lines[1].startswith(" " * 20)


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
    assert _field("Metrics", "Result F1, AST similarity") in header
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
