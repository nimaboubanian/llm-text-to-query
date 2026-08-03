"""Acceptance: re-score the archived 2026-08-01 qwen2.5-coder:7b run.

Expected values were measured against the real archived data while designing
spec A. They pin the whole metric change to 22 real queries at once, so a
regression in one query's handling can't hide behind another's.
"""
from pathlib import Path

import pytest

from text2query.benchmark.similarity import evaluate_query

RUN = Path("../benchmark/results/2026-08-01_02-19-06")
LLM_ANSWERS = RUN / "answers/qwen2.5-coder_7b/seed_1"
LLM_QUERIES = RUN / "queries/qwen2.5-coder_7b/seed_1"
GT_QUERIES = Path("../benchmark/.tpch/queries")
GT_ANSWERS = Path("../benchmark/.tpch/answers")

EX_EXPECTED = {"01", "03", "10", "16", "18"}
EXEC_ERRORS = {"07", "08", "13"}
# (query_id, precision, recall, f1) for the queries scoring partial credit.
PARTIAL = {
    "20": (0.7983, 1.0, 0.8878),
    "02": (0.7300, 0.7300, 0.7300),
    "15": (0.0001, 1.0, 0.0002),
}


def _require_archive():
    if not (LLM_ANSWERS.exists() and GT_ANSWERS.exists()):
        pytest.skip("archived benchmark run not present (gitignored data)")


def _score_all() -> dict[str, dict]:
    _require_archive()
    results = {}
    for gt_sql in sorted(GT_QUERIES.glob("*.sql")):
        qid = gt_sql.stem
        results[qid] = evaluate_query(
            query_id=int(qid),
            gt_csv=GT_ANSWERS / f"{qid}.csv",
            llm_csv=LLM_ANSWERS / f"{qid}.csv",
            gt_sql=gt_sql,
            llm_sql=LLM_QUERIES / f"{qid}.sql",
        )
    return results


@pytest.fixture(scope="module")
def scored():
    return _score_all()


def test_execution_accuracy_is_five_of_twentytwo(scored):
    passing = {qid for qid, r in scored.items() if r["execution_accuracy"] == 1}
    assert passing == EX_EXPECTED
    assert sum(r["execution_accuracy"] for r in scored.values()) == 5


def test_superset_and_partial_answers_score_zero_ex(scored):
    """Q20's superset (F1 0.8878) and Q15's 10k-row dump must not read as correct."""
    for qid, (prec, rec, f1) in PARTIAL.items():
        assert scored[qid]["execution_accuracy"] == 0, qid
        assert scored[qid]["result_precision"] == pytest.approx(prec, abs=1e-4), qid
        assert scored[qid]["result_recall"] == pytest.approx(rec, abs=1e-4), qid
        assert scored[qid]["result_f1"] == pytest.approx(f1, abs=1e-4), qid


def test_execution_errors_score_zero(scored):
    for qid in EXEC_ERRORS:
        assert scored[qid]["status"] == "exec_error", qid
        assert scored[qid]["execution_accuracy"] == 0, qid
        assert scored[qid]["result_f1"] == 0.0, qid


def test_no_missing_rows_and_mean_f1_matches(scored):
    assert all(r["status"] != "missing" for r in scored.values())
    mean_f1 = sum(r["result_f1"] for r in scored.values()) / len(scored)
    assert mean_f1 == pytest.approx(0.3008, abs=1e-3)


def test_ordering_requirement_costs_no_passing_query(scored):
    """Every EX=1 query is verified sorted, so §2 adds no false negatives."""
    for qid in EX_EXPECTED:
        assert scored[qid]["result_f1"] == 1.0, qid
        assert scored[qid]["execution_accuracy"] == 1, qid


def test_shuffling_a_correct_answer_breaks_ex(tmp_path):
    """Negative control: the ordering check is not vacuous."""
    _require_archive()
    import pandas as pd
    from text2query.benchmark.similarity import _execution_accuracy

    for qid in ["01", "03", "10", "18"]:
        gt_csv = GT_ANSWERS / f"{qid}.csv"
        shuffled = tmp_path / f"{qid}.csv"
        pd.read_csv(LLM_ANSWERS / f"{qid}.csv").sample(
            frac=1, random_state=0,
        ).to_csv(shuffled, index=False)
        ref_sql = (GT_QUERIES / f"{qid}.sql").read_text()

        assert _execution_accuracy("ok", 1.0, 1.0, gt_csv, shuffled, ref_sql) == 0, qid
