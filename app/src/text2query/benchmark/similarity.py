import math
import re
from collections import Counter
from itertools import permutations
from pathlib import Path

import pandas as pd
import sqlglot
from sqlglot import exp
from sqlglot.diff import Keep, diff


def evaluate_query(
    query_id: int,
    gt_csv: Path,
    llm_csv: Path,
    gt_sql: Path,
    llm_sql: Path,
) -> dict:
    gt_sql_text = gt_sql.read_text() if gt_sql.exists() else ""
    llm_sql_text = llm_sql.read_text() if llm_sql.exists() else ""

    status, exact_match, precision, recall, f1, error_detail = _result_set_comparison(
        gt_csv, llm_csv, ref_sql=gt_sql_text,
    )

    error_category = None
    if status == "exec_error" and error_detail:
        error_category = _classify_error(llm_sql_text, error_detail)

    ast_sim = _ast_similarity(gt_sql_text, llm_sql_text)
    clause_scores = _clause_level_scores(gt_sql_text, llm_sql_text)
    composite = _composite_score(
        result_f1=f1,
        ast_sim=ast_sim if ast_sim is not None else 0.0,
    )

    return {
        "query_id": query_id,
        "status": status,
        "exact_match": exact_match,
        "result_precision": _round(precision),
        "result_recall": _round(recall),
        "result_f1": _round(f1),
        "ast_similarity": _round(ast_sim),
        "error_category": error_category,
        "composite_score": _round(composite),
        "clause_scores": clause_scores,
    }


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


_DEFAULT_WEIGHTS = {"f1": 0.60, "ast": 0.40}


def _composite_score(
    result_f1: float | None,
    ast_sim: float,
    weights: dict | None = None,
) -> float:
    w = weights or _DEFAULT_WEIGHTS
    components = {"ast": ast_sim}
    w_total = w["ast"]

    if result_f1 is not None:
        components["f1"] = result_f1
        w_total += w["f1"]

    return sum(w[k] * v for k, v in components.items()) / w_total if w_total > 0 else 0.0




def _clause_level_scores(ref_sql: str, gen_sql: str) -> dict | None:
    def extract(sql):
        try:
            tree = sqlglot.parse_one(sql, dialect="postgres")
        except Exception:
            return None
        select_node = tree.find(exp.Select)
        select_str = ", ".join(e.sql() for e in select_node.expressions) if select_node else None
        return {
            "select": select_str,
            "from": str(tree.find(exp.From)) if tree.find(exp.From) else None,
            "where": str(tree.find(exp.Where)) if tree.find(exp.Where) else None,
            "group_by": str(tree.find(exp.Group)) if tree.find(exp.Group) else None,
            "having": str(tree.find(exp.Having)) if tree.find(exp.Having) else None,
            "order_by": str(tree.find(exp.Order)) if tree.find(exp.Order) else None,
            "limit": str(tree.find(exp.Limit)) if tree.find(exp.Limit) else None,
        }

    ref = extract(ref_sql)
    gen = extract(gen_sql)
    if ref is None or gen is None:
        return None

    scores = {}
    for clause in ("select", "from", "where", "group_by", "having", "order_by", "limit"):
        r, g = ref[clause], gen[clause]
        if r is None and g is None:
            scores[clause] = 1.0
        elif r is None or g is None:
            scores[clause] = 0.0
        else:
            scores[clause] = 1.0 if r == g else 0.0
    return scores



def _classify_error(sql: str, error_text: str) -> str:
    error_lower = error_text.lower()

    try:
        sqlglot.parse_one(sql, dialect="postgres", error_level=sqlglot.ErrorLevel.RAISE)
    except sqlglot.errors.ParseError:
        return "SyntaxError"
    except Exception:
        pass

    schema_patterns = [
        r"relation .+ does not exist",
        r"column .+ does not exist",
        r"table .+ doesn't exist",
        r"undefined table",
        r"unknown column",
    ]
    if any(re.search(p, error_lower) for p in schema_patterns):
        return "SchemaMismatch"

    if any(kw in error_lower for kw in ("timeout", "cancelled", "statement_timeout")):
        return "Timeout"

    runtime_patterns = [
        r"division by zero",
        r"invalid input syntax",
        r"cannot be cast",
        r"ambiguous column",
        r"operator does not exist",
    ]
    if any(re.search(p, error_lower) for p in runtime_patterns):
        return "RuntimeError"

    return "Unknown"


def _align_columns(ref_df: pd.DataFrame, gen_df: pd.DataFrame) -> pd.DataFrame:
    if list(ref_df.columns) == list(gen_df.columns):
        return gen_df
    if len(ref_df.columns) != len(gen_df.columns):
        return gen_df
    n = len(gen_df.columns)
    if n > 8:
        return gen_df

    best_perm = list(range(n))
    best_score = -1
    for perm in permutations(range(n)):
        reordered = gen_df.iloc[:, list(perm)]
        reordered.columns = ref_df.columns
        score = sum(
            len(set(ref_df[c].astype(str)) & set(reordered[c].astype(str)))
            for c in ref_df.columns
        )
        if score > best_score:
            best_score = score
            best_perm = list(perm)

    aligned = gen_df.iloc[:, best_perm].copy()
    aligned.columns = ref_df.columns
    return aligned


def _has_top_level_order_limit(sql: str) -> bool:
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
        return tree.args.get("order") is not None and tree.args.get("limit") is not None
    except Exception:
        return "ORDER BY" in sql.upper() and "LIMIT" in sql.upper()


def _result_set_comparison(
    gt_csv: Path, llm_csv: Path, ref_sql: str = "", float_epsilon: float = 1e-4,
) -> tuple[str, bool | None, float | None, float | None, float | None, str | None]:
    if not llm_csv.exists():
        return "missing", None, None, None, None, None

    content = llm_csv.read_text()
    first_line = content.split("\n", 1)[0].strip()
    if first_line == "ERROR":
        error_detail = content.split("\n", 1)[1].strip() if "\n" in content else ""
        return "exec_error", False, 0.0, 0.0, 0.0, error_detail

    gt_df = pd.read_csv(gt_csv)
    llm_df = pd.read_csv(llm_csv)

    if len(gt_df) == 0 and len(llm_df) == 0:
        return "ok", True, 1.0, 1.0, 1.0, None

    if len(gt_df.columns) != len(llm_df.columns):
        return "ok", False, 0.0, 0.0, 0.0, None

    llm_df = _align_columns(gt_df, llm_df)

    precision_digits = max(0, int(-math.floor(math.log10(float_epsilon)))) if float_epsilon > 0 else 4
    for df in (gt_df, llm_df):
        for col in df.select_dtypes(include=["float"]).columns:
            df[col] = df[col].round(precision_digits)
        df.fillna("NULL", inplace=True)

    if _has_top_level_order_limit(ref_sql):
        min_len = min(len(gt_df), len(llm_df))
        matches = sum(
            tuple(gt_df.iloc[i]) == tuple(llm_df.iloc[i])
            for i in range(min_len)
        )
        exact_match = len(gt_df) == len(llm_df) and matches == len(gt_df)
        precision = matches / len(llm_df) if len(llm_df) > 0 else 0.0
        recall = matches / len(gt_df) if len(gt_df) > 0 else 0.0
    else:
        gt_rows = Counter(tuple(row) for row in gt_df.itertuples(index=False, name=None))
        llm_rows = Counter(tuple(row) for row in llm_df.itertuples(index=False, name=None))
        exact_match = gt_rows == llm_rows
        matched = sum((gt_rows & llm_rows).values())
        total_llm = sum(llm_rows.values())
        total_gt = sum(gt_rows.values())
        precision = matched / total_llm if total_llm > 0 else 0.0
        recall = matched / total_gt if total_gt > 0 else 0.0

    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return "ok", exact_match, precision, recall, f1, None


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
