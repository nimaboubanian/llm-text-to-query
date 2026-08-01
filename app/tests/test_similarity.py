import pytest
import pandas as pd
from pathlib import Path

from text2query.benchmark.similarity import (
    _ast_similarity, _ast_similarity_normalized, _classify_error,
    _result_set_comparison, _tpch_schema, _order_spec, _is_sorted_by,
    _execution_accuracy, evaluate_query,
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
        """Order is no longer folded into F1 — it is carried by EX (spec §1)."""
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("id\n1\n2\n3\n")
        llm.write_text("id\n3\n2\n1\n")

        status, prec, rec, f1, err = _result_set_comparison(
            gt, llm, ref_sql="SELECT id FROM t ORDER BY id LIMIT 3",
        )
        assert status == "ok"
        assert f1 == 1.0
        assert _execution_accuracy(
            status, prec, rec, gt, llm, "SELECT id FROM t ORDER BY id LIMIT 3",
        ) == 0

    def test_column_reorder_alignment(self, tmp_path):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("a,b\n1,x\n2,y\n")
        llm.write_text("b,a\nx,1\ny,2\n")

        status, prec, rec, f1, err = _result_set_comparison(gt, llm)
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

    def test_int_columns_use_exact_match_not_epsilon(self, tmp_path):
        # Spec: only floats get epsilon tolerance. Integer columns must stay
        # exact-match even with a loose epsilon, or adjacent IDs would
        # falsely collapse together.
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text("id\n4\n5\n")
        llm.write_text("id\n5\n6\n")

        status, prec, rec, f1, _ = _result_set_comparison(gt, llm, eps=1.0)
        assert status == "ok"
        assert f1 == pytest.approx(0.5)  # only the exact "5" match counts

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

    def test_many_columns_with_renamed_llm_columns_does_not_crash(self, tmp_path):
        # >8 columns skips _align_columns's permutation search; the LLM using
        # different column names/aliases than the reference must not KeyError.
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        cols_gt = ",".join(f"c{i}" for i in range(9))
        cols_llm = ",".join(f"total_{i}" for i in range(9))
        row = ",".join(str(i) for i in range(9))
        gt.write_text(f"{cols_gt}\n{row}\n")
        llm.write_text(f"{cols_llm}\n{row}\n")

        status, prec, rec, f1, err = _result_set_comparison(gt, llm)
        assert status == "ok"

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


class TestOrderSpec:
    def test_extracts_column_and_direction(self):
        spec = _order_spec("SELECT a, b FROM t ORDER BY a DESC, b")
        assert spec == [("a", True), ("b", False)]

    def test_strips_table_qualifier(self):
        # TPC-H Q03 orders by o.o_orderdate; the CSV column is o_orderdate.
        spec = _order_spec("SELECT x FROM t o ORDER BY o.o_orderdate")
        assert spec == [("o_orderdate", False)]

    def test_no_order_by_returns_none(self):
        assert _order_spec("SELECT sum(x) FROM t") is None

    def test_unparseable_sql_returns_none(self):
        assert _order_spec("this is not sql ((") is None

    def test_empty_sql_returns_none(self):
        assert _order_spec("") is None


class TestIsSortedBy:
    def test_correctly_sorted_ascending(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        assert _is_sorted_by(df, [("a", False)]) is True

    def test_wrong_order_detected(self):
        df = pd.DataFrame({"a": [3, 2, 1]})
        assert _is_sorted_by(df, [("a", False)]) is False

    def test_descending_key(self):
        df = pd.DataFrame({"a": [3, 2, 1]})
        assert _is_sorted_by(df, [("a", True)]) is True

    def test_mixed_directions(self):
        df = pd.DataFrame({"a": [1, 1, 2], "b": [9, 5, 7]})
        assert _is_sorted_by(df, [("a", False), ("b", True)]) is True
        assert _is_sorted_by(df, [("a", False), ("b", False)]) is False

    def test_ties_may_permute(self):
        # Rows tied on the key may appear in any order — the non-key column
        # is not part of the ordering requirement.
        df = pd.DataFrame({"k": [1, 1, 2], "other": ["z", "a", "m"]})
        assert _is_sorted_by(df, [("k", False)]) is True

    def test_missing_key_column_returns_none(self):
        df = pd.DataFrame({"a": [1, 2]})
        assert _is_sorted_by(df, [("nope", False)]) is None

    def test_nan_in_key_column_returns_none(self):
        # Postgres and pandas disagree on NULL placement for DESC; rather than
        # emulate it, skip the check so a model is never wrongly penalised.
        df = pd.DataFrame({"a": [1.0, float("nan"), 2.0]})
        assert _is_sorted_by(df, [("a", False)]) is None

    def test_single_row_is_trivially_sorted(self):
        df = pd.DataFrame({"a": [42]})
        assert _is_sorted_by(df, [("a", False)]) is True


def test_order_spec_resolves_for_every_tpch_reference():
    """Every reference query's ORDER BY keys must be extractable; spec §2."""
    import pathlib
    queries = sorted(pathlib.Path("../benchmark/.tpch/queries").glob("*.sql"))
    if not queries:
        pytest.skip("TPC-H reference queries not available")
    assert len(queries) == 22

    ordered = {}
    for q in queries:
        spec = _order_spec(q.read_text())
        if spec is not None:
            ordered[q.stem] = spec

    # 18 of 22 have a top-level ORDER BY; 06/14/17/19 are single-row aggregates.
    assert len(ordered) == 18
    assert set(ordered) == {
        "01", "02", "03", "04", "05", "07", "08", "09", "10", "11",
        "12", "13", "15", "16", "18", "20", "21", "22",
    }
    # Q03's key is table-qualified in the SQL and must arrive unqualified.
    assert ("o_orderdate", False) in ordered["03"]


class TestExecutionAccuracy:
    def _files(self, tmp_path, gt_text, llm_text):
        gt = tmp_path / "gt.csv"
        llm = tmp_path / "llm.csv"
        gt.write_text(gt_text)
        llm.write_text(llm_text)
        return gt, llm

    def test_perfect_match_unordered_reference_scores_one(self, tmp_path):
        gt, llm = self._files(tmp_path, "id\n1\n2\n", "id\n1\n2\n")
        assert _execution_accuracy("ok", 1.0, 1.0, gt, llm, "SELECT id FROM t") == 1

    def test_superset_scores_zero(self, tmp_path):
        # The Q20 failure mode: recall 1.0 but extra rows -> not correct.
        gt, llm = self._files(tmp_path, "id\n1\n2\n", "id\n1\n2\n3\n")
        status, prec, rec, f1, _ = _result_set_comparison(gt, llm)
        assert rec == 1.0 and prec < 1.0
        assert _execution_accuracy(status, prec, rec, gt, llm, "SELECT id FROM t") == 0

    def test_right_rows_wrong_order_scores_zero(self, tmp_path):
        gt, llm = self._files(tmp_path, "id\n1\n2\n3\n", "id\n3\n2\n1\n")
        status, prec, rec, f1, _ = _result_set_comparison(gt, llm)
        assert f1 == 1.0  # bag-based F1 is blind to order, by design
        assert _execution_accuracy(
            status, prec, rec, gt, llm, "SELECT id FROM t ORDER BY id",
        ) == 0

    def test_right_rows_right_order_scores_one(self, tmp_path):
        gt, llm = self._files(tmp_path, "id\n1\n2\n3\n", "id\n1\n2\n3\n")
        assert _execution_accuracy(
            "ok", 1.0, 1.0, gt, llm, "SELECT id FROM t ORDER BY id",
        ) == 1

    def test_exec_error_scores_zero(self, tmp_path):
        gt, llm = self._files(tmp_path, "id\n1\n", "id\n1\n")
        assert _execution_accuracy("exec_error", 0.0, 0.0, gt, llm, "SELECT id FROM t") == 0

    def test_unmappable_order_key_does_not_penalise(self, tmp_path):
        # Harness limitation must never zero a correct-looking answer.
        gt, llm = self._files(tmp_path, "id\n1\n2\n", "id\n1\n2\n")
        assert _execution_accuracy(
            "ok", 1.0, 1.0, gt, llm, "SELECT id FROM t ORDER BY some_other_col",
        ) == 1


class TestEvaluateQueryReportsEX:
    def test_evaluate_query_includes_execution_accuracy(self, tmp_path):
        gt_csv = tmp_path / "gt.csv"
        llm_csv = tmp_path / "llm.csv"
        gt_csv.write_text("id\n1\n2\n")
        llm_csv.write_text("id\n1\n2\n")
        gt_sql = tmp_path / "gt.sql"
        llm_sql = tmp_path / "llm.sql"
        gt_sql.write_text("SELECT id FROM t ORDER BY id")
        llm_sql.write_text("SELECT id FROM t ORDER BY id")

        result = evaluate_query(1, gt_csv, llm_csv, gt_sql, llm_sql)
        assert result["execution_accuracy"] == 1
        assert result["result_f1"] == 1.0
