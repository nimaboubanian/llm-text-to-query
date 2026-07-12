import csv

from text2query.benchmark.reporting import (
    _format_per_query_similarity, _format_summary_similarity,
    _compute_stats, archive_session, generate_reports,
)



def test_per_query_has_all_metrics():
    result = {
        "result_f1": 0.85, "result_precision": 0.9,
        "result_recall": 0.8, "ast_similarity": 0.72,
    }
    output = _format_per_query_similarity(result)
    assert "Result F1" in output
    assert "Precision" in output
    assert "Recall" in output
    assert "AST Similarity" in output
    assert "0.8500" in output


def test_unknown_error_detail_shown_in_report():
    result = {
        "result_f1": None, "result_precision": None,
        "result_recall": None, "ast_similarity": None,
        "error_category": "Unknown",
        "error_detail": "could not determine data type of parameter $1",
    }
    output = _format_per_query_similarity(result)
    assert "Unknown" in output
    assert "could not determine data type" in output


def test_summary_per_query_table():
    results = [
        {"query_id": 1, "status": "ok", "result_f1": 1.0, "ast_similarity": 0.8, "result_precision": 1.0, "result_recall": 1.0},
        {"query_id": 2, "status": "exec_error", "result_f1": 0.0, "ast_similarity": 0.2, "result_precision": 0.0, "result_recall": 0.0},
        {"query_id": 3, "status": "missing", "result_f1": None, "ast_similarity": None, "result_precision": None, "result_recall": None},
    ]
    output = _format_summary_similarity(results)
    assert "01" in output
    assert "ok" in output
    assert "exec_error" in output
    assert "missing" in output
    assert "1.0000" in output


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


def test_archive_moves_files(tmp_path):
    queries = tmp_path / "queries"
    answers = tmp_path / "answers"
    report = tmp_path / "report"
    results_base = tmp_path / "results"
    queries.mkdir()
    answers.mkdir()
    report.mkdir()

    (queries / "01.sql").write_text("SELECT 1")
    (queries / "02.sql").write_text("SELECT 2")
    (answers / "01.csv").write_text("id\n1\n")

    session_dir = archive_session(queries, answers, report, results_base)

    assert session_dir.exists()
    assert (session_dir / "queries" / "01.sql").exists()
    assert (session_dir / "queries" / "02.sql").exists()
    assert (session_dir / "answers" / "01.csv").exists()
    # source dirs should be cleaned up
    assert not queries.exists()
    assert not answers.exists()


def test_results_csv_single_seed(tmp_path):
    """Single-model single-seed runs should emit results.csv with the new columns."""
    ref_queries = tmp_path / "ref_queries"
    ref_answers = tmp_path / "ref_answers"
    gen_queries = tmp_path / "gen_queries"
    gen_answers = tmp_path / "gen_answers"
    questions = tmp_path / "questions"
    report_dir = tmp_path / "report"
    for d in [ref_queries, ref_answers, gen_queries, gen_answers, questions]:
        d.mkdir()

    (ref_queries / "01.sql").write_text("SELECT name FROM customers;")
    (ref_answers / "01.csv").write_text("name\nAlice\n")
    (gen_queries / "01.sql").write_text("SELECT name FROM customers;")
    (gen_queries / "01.prompt").write_text("SCHEMA: customers(name)\nQuestion: list names")
    (gen_answers / "01.csv").write_text("name\nAlice\n")
    (questions / "01.md").write_text('# Business Question:\n  "What are the customer names?"\n')

    generate_reports(
        generated_queries_dir=gen_queries,
        reference_queries_dir=ref_queries,
        generated_answers_dir=gen_answers,
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
    assert r["seed"] == ""  # single-seed → blank
    assert r["model"] == "m1"
    assert r["query_id"] == "01"
    assert r["nl_query"] == "What are the customer names?"
    assert r["prompt"] == "SCHEMA: customers(name)\nQuestion: list names"
    assert r["generated_sql"] == "SELECT name FROM customers;"
    assert r["real_sql"] == "SELECT name FROM customers;"


def test_results_csv_missing_prompt_and_questions(tmp_path):
    """Without prompt file / questions_dir, prompt and nl_query degrade to empty."""
    ref_queries = tmp_path / "ref_queries"
    ref_answers = tmp_path / "ref_answers"
    gen_queries = tmp_path / "gen_queries"
    gen_answers = tmp_path / "gen_answers"
    report_dir = tmp_path / "report"
    for d in [ref_queries, ref_answers, gen_queries, gen_answers]:
        d.mkdir()

    (ref_queries / "01.sql").write_text("SELECT 1;")
    (ref_answers / "01.csv").write_text("col\n1\n")
    (gen_queries / "01.sql").write_text("SELECT 1;")
    (gen_answers / "01.csv").write_text("col\n1\n")

    generate_reports(
        generated_queries_dir=gen_queries,
        reference_queries_dir=ref_queries,
        generated_answers_dir=gen_answers,
        reference_answers_dir=ref_answers,
        report_dir=report_dir,
    )

    with open(report_dir / "results.csv") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["prompt"] == ""
    assert rows[0]["nl_query"] == ""
    assert rows[0]["real_sql"] == "SELECT 1;"


def test_archive_moves_error_files(tmp_path):
    queries = tmp_path / "queries"
    answers = tmp_path / "answers"
    report = tmp_path / "report"
    results_base = tmp_path / "results"
    queries.mkdir()
    answers.mkdir()

    (queries / "01.sql").write_text("SELECT 1")
    (answers / "01.error").write_text("division by zero")

    session_dir = archive_session(queries, answers, report, results_base)

    assert (session_dir / "answers" / "01.error").exists()
    assert (session_dir / "answers" / "01.error").read_text() == "division by zero"


def test_archive_empty_dirs(tmp_path):
    queries = tmp_path / "queries"
    answers = tmp_path / "answers"
    report = tmp_path / "report"
    results_base = tmp_path / "results"
    queries.mkdir()
    answers.mkdir()

    session_dir = archive_session(queries, answers, report, results_base)
    assert session_dir.exists()
    assert (session_dir / "queries").exists()
