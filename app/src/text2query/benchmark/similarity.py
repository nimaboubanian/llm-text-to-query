from collections import Counter
from pathlib import Path

import pandas as pd
import sqlglot
from sqlglot.diff import Keep, diff


def evaluate_query(
    query_id: int,
    gt_csv: Path,
    llm_csv: Path,
    gt_sql: Path,
    llm_sql: Path,
) -> dict:
    status, exact_match, precision, recall, f1 = _result_set_comparison(gt_csv, llm_csv)

    gt_sql_text = gt_sql.read_text() if gt_sql.exists() else ""
    llm_sql_text = llm_sql.read_text() if llm_sql.exists() else ""

    ast_sim = _ast_similarity(gt_sql_text, llm_sql_text)

    return {
        "query_id": query_id,
        "status": status,
        "exact_match": exact_match,
        "result_precision": _round(precision),
        "result_recall": _round(recall),
        "result_f1": _round(f1),
        "ast_similarity": _round(ast_sim),
    }


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _result_set_comparison(
    gt_csv: Path, llm_csv: Path,
) -> tuple[str, bool | None, float | None, float | None, float | None]:
    if not llm_csv.exists():
        return "missing", None, None, None, None

    first_line = llm_csv.read_text().split("\n", 1)[0].strip()
    if first_line == "ERROR":
        return "exec_error", False, 0.0, 0.0, 0.0

    gt_df = pd.read_csv(gt_csv)
    llm_df = pd.read_csv(llm_csv)

    if len(gt_df.columns) != len(llm_df.columns):
        return "ok", False, 0.0, 0.0, 0.0

    for df in (gt_df, llm_df):
        for col in df.select_dtypes(include=["float"]).columns:
            df[col] = df[col].round(4)
        df.fillna("NULL", inplace=True)

    gt_rows = Counter(tuple(row) for row in gt_df.itertuples(index=False, name=None))
    llm_rows = Counter(tuple(row) for row in llm_df.itertuples(index=False, name=None))

    matched = sum((gt_rows & llm_rows).values())
    total_llm = sum(llm_rows.values())
    total_gt = sum(gt_rows.values())

    precision = matched / total_llm if total_llm > 0 else 0.0
    recall = matched / total_gt if total_gt > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    exact_match = f1 == 1.0

    return "ok", exact_match, precision, recall, f1


def _ast_similarity(gt_sql: str, llm_sql: str) -> float | None:
    try:
        gt_tree = sqlglot.parse(gt_sql, dialect="postgres")[0]
        llm_tree = sqlglot.parse(llm_sql, dialect="postgres")[0]
        if gt_tree is None or llm_tree is None:
            return None
    except Exception:
        return None

    try:
        changes = diff(gt_tree, llm_tree)
    except Exception:
        return None

    kept = sum(1 for c in changes if isinstance(c, Keep))
    edits = sum(1 for c in changes if not isinstance(c, Keep))

    total = kept + edits
    return kept / total if total > 0 else 1.0
