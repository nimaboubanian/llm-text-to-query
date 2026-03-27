from text2query.benchmark.reporting import (
    _v, _format_per_query_similarity, _format_summary_similarity,
    _compute_stats, archive_session,
)


def test_v_formats_float():
    assert _v(0.9123) == "0.9123"
    assert _v(1.0) == "1.0000"


def test_v_formats_bool():
    assert _v(True) == "Yes"
    assert _v(False) == "No"


def test_v_formats_none():
    assert _v(None) == "—"


def test_per_query_has_all_metrics():
    result = {
        "result_f1": 0.85, "result_precision": 0.9,
        "result_recall": 0.8, "exact_match": False,
        "ast_similarity": 0.72,
    }
    output = _format_per_query_similarity(result)
    assert "Result F1" in output
    assert "Precision" in output
    assert "Recall" in output
    assert "Exact Match" in output
    assert "AST Similarity" in output
    assert "0.8500" in output


def test_summary_computes_averages():
    results = [
        {"query_id": 1, "status": "ok", "exact_match": True, "result_f1": 1.0, "ast_similarity": 0.8, "result_precision": 1.0, "result_recall": 1.0},
        {"query_id": 2, "status": "ok", "exact_match": False, "result_f1": 0.5, "ast_similarity": 0.6, "result_precision": 0.5, "result_recall": 0.5},
    ]
    output = _format_summary_similarity(results)
    assert "1 / 2" in output
    assert "0.7500" in output  # avg F1 = (1.0 + 0.5) / 2
    assert "0.7000" in output  # avg AST = (0.8 + 0.6) / 2


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
