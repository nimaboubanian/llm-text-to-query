import pytest
from pathlib import Path

from text2query.benchmark.similarity import _ast_similarity, _round, _result_set_comparison


class TestAstSimilarity:
    def test_identical_sql(self):
        sql = "SELECT id, name FROM users WHERE active = true"
        assert _ast_similarity(sql, sql) == 1.0

    def test_different_sql_returns_partial(self):
        gt = "SELECT name FROM users WHERE id = 1"
        llm = "SELECT name, email FROM users WHERE id > 0"
        sim = _ast_similarity(gt, llm)
        assert sim is not None
        assert 0.0 < sim < 1.0

    def test_nonsense_input_scores_low(self):
        # sqlglot parses nonsense as identifiers, yielding a tiny score
        score = _ast_similarity("this is not sql", "neither is this")
        assert score is not None
        assert score < 0.2

    def test_empty_string_returns_none(self):
        assert _ast_similarity("", "") is None


def test_round_none():
    assert _round(None) is None


def test_round_truncates():
    assert _round(0.123456789) == 0.1235


def test_round_preserves_short():
    assert _round(0.5) == 0.5


class TestResultSetComparison:
    def test_exact_match(self, tmp_path):
        csv_content = "id,name\n1,alice\n2,bob\n"
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text(csv_content)
        llm.write_text(csv_content)

        status, exact, prec, rec, f1 = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert exact is True
        assert f1 == 1.0

    def test_partial_overlap(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("id\n1\n2\n3\n")
        llm.write_text("id\n2\n3\n4\n")

        status, exact, prec, rec, f1 = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert exact is False
        assert prec == pytest.approx(2 / 3, abs=0.01)
        assert rec == pytest.approx(2 / 3, abs=0.01)

    def test_missing_llm_csv(self, tmp_path):
        gt = tmp_path / "gt.csv"
        gt.write_text("id\n1\n")
        missing = tmp_path / "nope.csv"

        status, exact, prec, rec, f1 = _result_set_comparison(gt, missing)
        assert status == "missing"
        assert exact is None

    def test_error_csv(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("id\n1\n")
        llm.write_text("ERROR\nsome failure\n")

        status, exact, prec, rec, f1 = _result_set_comparison(gt, llm)
        assert status == "exec_error"
        assert f1 == 0.0

    def test_column_count_mismatch(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("a,b\n1,2\n")
        llm.write_text("x\n1\n")

        status, exact, prec, rec, f1 = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert exact is False
        assert f1 == 0.0
