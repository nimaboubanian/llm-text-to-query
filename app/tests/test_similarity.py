import pytest
from pathlib import Path

from text2query.benchmark.similarity import (
    _ast_similarity, _ast_similarity_normalized, _classify_error,
    _result_set_comparison, _tpch_schema,
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



class TestAstSimilarityNormalized:
    def test_tpch_schema_parsed(self):
        schema = _tpch_schema()
        assert len(schema) == 8
        assert "l_orderkey" in schema["lineitem"]

    def test_alias_divergence_normalizes_to_perfect(self):
        gt = "SELECT c.c_name FROM customer AS c"
        llm = "SELECT customer.c_name FROM customer"
        raw = _ast_similarity(gt, llm)
        assert raw is not None and raw < 1.0
        assert _ast_similarity_normalized(gt, llm) == 1.0

    def test_predicate_reorder_normalizes_to_perfect(self):
        gt = "SELECT c_name FROM customer WHERE c_acctbal > 100 AND c_nationkey = 3"
        llm = "SELECT c_name FROM customer WHERE c_nationkey = 3 AND c_acctbal > 100"
        assert _ast_similarity_normalized(gt, llm) == 1.0

    def test_self_join_aliases_survive(self):
        # Both aliases reference the same table, so stripping is skipped and
        # a/b must stay distinct. Using the *same* query on both sides would
        # be tautological (identical trees score 1.0 whether or not the
        # collision guard exists) so this pins gt/llm selecting from opposite
        # sides of the self-join: if the guard were removed and both aliases
        # collapsed to "lineitem", these would falsely normalize to the same
        # tree and score 1.0.
        gt = (
            "SELECT a.l_orderkey FROM lineitem AS a "
            "JOIN lineitem AS b ON a.l_orderkey = b.l_orderkey"
        )
        llm = (
            "SELECT b.l_orderkey FROM lineitem AS a "
            "JOIN lineitem AS b ON a.l_orderkey = b.l_orderkey"
        )
        assert _ast_similarity_normalized(gt, llm) < 1.0

    def test_unparseable_returns_none(self):
        assert _ast_similarity_normalized("", "") is None

    def test_optimizer_failure_falls_back_to_raw(self, monkeypatch):
        import text2query.benchmark.similarity as sim

        def boom():
            raise RuntimeError("schema unavailable")

        monkeypatch.setattr(sim, "_tpch_schema", boom)
        gt = "SELECT c.c_name FROM customer AS c"
        llm = "SELECT customer.c_name FROM customer"
        assert sim._ast_similarity_normalized(gt, llm) == sim._ast_similarity(gt, llm)


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

    def test_error_sidecar_file(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        error_file = tmp_path / "llm.error"
        gt.write_text("id\n1\n")
        error_file.write_text("some failure")

        status, prec, rec, f1, err = _result_set_comparison(gt, llm)
        assert status == "exec_error"
        assert f1 == 0.0
        assert err == "some failure"

    def test_real_error_column_treated_as_data(self, tmp_path):
        """A result set with a legitimate column literally named ERROR is not
        mistaken for a failed execution — only a sidecar .error file signals that."""
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("ERROR\nsome failure\n")
        llm.write_text("ERROR\nsome failure\n")

        status, prec, rec, f1, err = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert f1 == 1.0

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

    def test_tiny_float_noise_within_epsilon(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("val\n1.12340001\n")
        llm.write_text("val\n1.12339999\n")

        # Within default epsilon (1e-4), both match
        status, _, _, f1, _ = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert f1 == 1.0

    def test_epsilon_boundary_and_beyond(self, tmp_path):
        # 1.12345 vs 1.12354 straddle the old round(4) boundary but differ by
        # 9e-5 < 1e-4 -> match; 2.0 vs 2.001 differ by 1e-3 > 1e-4 -> no match
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("val\n1.12345\n2.0\n")
        llm.write_text("val\n1.12354\n2.001\n")

        status, prec, rec, f1, _ = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert prec == pytest.approx(0.5)
        assert rec == pytest.approx(0.5)

    def test_custom_epsilon_loosens_match(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("val\n100.0\n")
        llm.write_text("val\n100.005\n")

        _, _, _, f1_default, _ = _result_set_comparison(gt, llm)
        _, _, _, f1_loose, _ = _result_set_comparison(gt, llm, eps=1e-2)
        assert f1_default == 0.0
        assert f1_loose == 1.0

    def test_nan_matches_nan(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("name,val\na,1.5\nb,\n")
        llm.write_text("name,val\nb,\na,1.5\n")

        status, _, _, f1, _ = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert f1 == 1.0

    def test_ordered_mode_uses_epsilon(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("val\n1.00001\n2.0\n")
        llm.write_text("val\n1.00002\n2.0\n")

        status, _, _, f1, _ = _result_set_comparison(
            gt, llm, ref_sql="SELECT val FROM t ORDER BY val LIMIT 2",
        )
        assert status == "ok"
        assert f1 == 1.0

    def test_no_cross_key_float_matching(self, tmp_path):
        # floats are grouped under their exact non-float key; a's 1.0 must not
        # match b's 1.0
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("name,val\na,1.0\nb,2.0\n")
        llm.write_text("name,val\na,2.0\nb,1.0\n")

        status, _, _, f1, _ = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert f1 == 0.0

    def test_sorted_greedy_matching_resolves_near_ties(self, tmp_path):
        # When multiple gt values can each match multiple llm values (near-ties),
        # sorting before greedy matching ensures optimal pairing.
        # gt:  1.00000, 1.00009 (both within 1e-4 of 1.00005)
        # llm: 1.00005, 0.99995 (neither within 1e-4 of 1.00009)
        # Optimal: pair 1.00000 with 0.99995, 1.00009 with 1.00005 → 2 matches
        # Unsorted greedy would pair 1.00000 with 1.00005 first, leaving 1.00009
        # unmatched → 1 match (incorrect)
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("val\n1.00000\n1.00009\n")
        llm.write_text("val\n1.00005\n0.99995\n")

        status, prec, rec, f1, _ = _result_set_comparison(gt, llm)
        assert status == "ok"
        assert f1 == 1.0  # Both rows match with sorting+greedy
        assert prec == 1.0
        assert rec == 1.0
