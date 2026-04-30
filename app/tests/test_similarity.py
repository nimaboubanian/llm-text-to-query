import pytest
from pathlib import Path

from text2query.benchmark.similarity import (
    _ast_similarity, _classify_error,
    _round, _result_set_comparison,
)


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

    def test_predicate_reorder_scores_high(self):
        # Without normalization, predicate reordering produces a structural
        # difference — score is high but not perfect, which is correct.
        sql_a = "SELECT * FROM t WHERE a = 1 AND b = 2"
        sql_b = "SELECT * FROM t WHERE b = 2 AND a = 1"
        score = _ast_similarity(sql_a, sql_b)
        assert score is not None
        assert score > 0.8

    def test_between_vs_dual_inequality(self):
        # Without normalization these are structurally distinct AST forms;
        # 0.5 is the expected honest score.
        sql_between = "SELECT * FROM t WHERE x BETWEEN 1 AND 10"
        sql_dual = "SELECT * FROM t WHERE x >= 1 AND x <= 10"
        score = _ast_similarity(sql_between, sql_dual)
        assert score is not None
        assert score >= 0.5



def test_round_none():
    assert _round(None) is None


def test_round_truncates():
    assert _round(0.123456789) == 0.1235


def test_round_preserves_short():
    assert _round(0.5) == 0.5



class TestClassifyError:
    def test_schema_mismatch(self):
        sql = "SELECT x FROM nonexistent"
        assert _classify_error(sql, 'relation "nonexistent" does not exist') == "SchemaMismatch"

    def test_column_not_exist(self):
        sql = "SELECT bad_col FROM users"
        assert _classify_error(sql, 'column "bad_col" does not exist') == "SchemaMismatch"

    def test_function_not_exist(self):
        sql = "SELECT datediff(o.orderdate, CURRENT_DATE) FROM orders o"
        assert _classify_error(sql, 'function datediff(date, date) does not exist') == "SchemaMismatch"

    def test_timeout(self):
        sql = "SELECT * FROM big_table"
        assert _classify_error(sql, "canceling statement due to statement_timeout") == "Timeout"

    def test_runtime_error(self):
        sql = "SELECT 1/0 FROM t"
        assert _classify_error(sql, "division by zero") == "RuntimeError"

    def test_subquery_cardinality(self):
        sql = "SELECT * FROM t WHERE id = (SELECT id FROM t)"
        assert _classify_error(sql, "more than one row returned by a subquery used as an expression") == "RuntimeError"

    def test_postgres_syntax_error_text(self):
        # sqlglot may accept this, but PostgreSQL rejects it
        sql = "SELECT FROM orders"
        assert _classify_error(sql, 'syntax error at or near "FROM"') == "SyntaxError"

    def test_unknown_error(self):
        sql = "SELECT * FROM t"
        assert _classify_error(sql, "something completely unexpected") == "Unknown"



class TestResultSetComparison:
    def test_exact_match(self, tmp_path):
        csv_content = "id,name\n1,alice\n2,bob\n"
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text(csv_content)
        llm.write_text(csv_content)

        status, prec, rec, f1, err = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert f1 == 1.0

    def test_partial_overlap(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("id\n1\n2\n3\n")
        llm.write_text("id\n2\n3\n4\n")

        status, prec, rec, f1, err = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert prec == pytest.approx(2 / 3, abs=0.01)
        assert rec == pytest.approx(2 / 3, abs=0.01)

    def test_missing_llm_csv(self, tmp_path):
        gt = tmp_path / "gt.csv"
        gt.write_text("id\n1\n")
        missing = tmp_path / "nope.csv"

        status, prec, rec, f1, err = _result_set_comparison(gt, missing)
        assert status == "missing"
        assert prec is None

    def test_error_csv(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("id\n1\n")
        llm.write_text("ERROR\nsome failure\n")

        status, prec, rec, f1, err = _result_set_comparison(gt, llm)
        assert status == "exec_error"
        assert f1 == 0.0
        assert err == "some failure"

    def test_column_count_mismatch(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("a,b\n1,2\n")
        llm.write_text("x\n1\n")

        status, prec, rec, f1, err = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert f1 == 0.0

    def test_both_empty_result_sets(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("id,name\n")
        llm.write_text("id,name\n")

        status, prec, rec, f1, err = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert f1 == 1.0

    def test_ordered_comparison_correct_order(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("id\n1\n2\n3\n")
        llm.write_text("id\n1\n2\n3\n")

        status, prec, rec, f1, err = _result_set_comparison(
            gt, llm, ref_sql="SELECT id FROM t ORDER BY id LIMIT 3",
        )
        assert status == "ok"
        assert f1 == 1.0

    def test_ordered_comparison_wrong_order(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("id\n1\n2\n3\n")
        llm.write_text("id\n3\n2\n1\n")

        status, prec, rec, f1, err = _result_set_comparison(
            gt, llm, ref_sql="SELECT id FROM t ORDER BY id LIMIT 3",
        )
        assert status == "ok"
        assert f1 < 1.0

    def test_column_reorder_alignment(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("a,b\n1,x\n2,y\n")
        llm.write_text("b,a\nx,1\ny,2\n")

        status, prec, rec, f1, err = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert f1 == 1.0

    def test_custom_epsilon(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("val\n1.1234\n")
        llm.write_text("val\n1.1256\n")

        # Default epsilon 1e-4 (4 decimal places): 1.1234 != 1.1256
        status1, _, _, f1_strict, _ = _result_set_comparison(gt, llm)
        # Loose epsilon 1e-1 (1 decimal place): both round to 1.1
        status2, _, _, f1_loose, _ = _result_set_comparison(gt, llm, float_epsilon=1e-1)
        assert f1_strict == 0.0
        assert f1_loose == 1.0
