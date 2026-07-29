import csv
from pathlib import Path

from text2query.benchmark.reporting import (
    _compute_stats, generate_reports, format_run_summary,
    METRICS, METRIC_LABELS,
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
