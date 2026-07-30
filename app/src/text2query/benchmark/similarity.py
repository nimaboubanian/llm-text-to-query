"""Scoring: result-set and AST similarity metrics between generated and reference SQL."""
import logging
import re
from collections import Counter
from functools import lru_cache
from itertools import permutations
from pathlib import Path

import pandas as pd
import sqlglot
from sqlglot import exp
from sqlglot.diff import Keep, diff
from sqlglot.optimizer import optimize

from text2query.core.config import BENCHMARK_FLOAT_EPSILON

logger = logging.getLogger(__name__)


def evaluate_query(
    query_id: int,
    gt_csv: Path,
    llm_csv: Path,
    gt_sql: Path,
    llm_sql: Path,
) -> dict:
    gt_sql_text = gt_sql.read_text() if gt_sql.exists() else ""
    llm_sql_text = llm_sql.read_text() if llm_sql.exists() else ""

    status, precision, recall, f1, error_detail = _result_set_comparison(
        gt_csv, llm_csv, ref_sql=gt_sql_text,
    )

    error_category = None
    if status == "exec_error" and error_detail:
        error_category = _classify_error(llm_sql_text, error_detail)

    trees = _parse_pair(gt_sql_text, llm_sql_text)
    ast_sim = _diff_score(*trees) if trees else None
    ast_sim_norm = _diff_score(_normalize(trees[0]), _normalize(trees[1])) if trees else None

    return {
        "query_id": query_id,
        "status": status,
        "result_precision": _round(precision),
        "result_recall": _round(recall),
        "result_f1": _round(f1),
        "ast_similarity": _round(ast_sim),
        "ast_similarity_normalized": _round(ast_sim_norm),
        "error_category": error_category,
    }


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None




def _classify_error(sql: str, error_text: str) -> str:
    error_lower = error_text.lower()

    try:
        sqlglot.parse_one(sql, dialect="postgres", error_level=sqlglot.ErrorLevel.RAISE)
    except sqlglot.errors.ParseError:
        return "SyntaxError"
    except Exception as e:
        logger.debug("Unexpected error classifying SQL error: %s", e)

    # sqlglot is more lenient than PostgreSQL; check the actual error text too
    if any(re.search(p, error_lower) for p in (
        r"syntax error at or near",
        r"unterminated quoted string",
        r"unexpected end of input",
    )):
        return "SyntaxError"

    schema_patterns = [
        r"relation .+ does not exist",
        r"column .+ does not exist",
        r"function .+ does not exist",
    ]
    if any(re.search(p, error_lower) for p in schema_patterns):
        return "SchemaMismatch"

    if any(kw in error_lower for kw in ("timeout", "statement_timeout", "canceling")):
        return "Timeout"

    runtime_patterns = [
        r"division by zero",
        r"invalid input syntax",
        r"cannot be cast",
        r"ambiguous column",
        r"operator does not exist",
        r"more than one row returned by a subquery",
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
        # Too many columns for permutation search; still align labels
        # positionally so callers can index gen_df by ref_df's column names.
        return gen_df.set_axis(ref_df.columns, axis=1)

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
    except Exception as e:
        logger.debug("Failed to parse SQL for order/limit check, falling back to keyword search: %s", e)
        return "ORDER BY" in sql.upper() and "LIMIT" in sql.upper()


def _num_eq(a, b, eps: float) -> bool:
    """Two numeric cells match when both are NaN or within eps of each other."""
    if pd.isna(a) or pd.isna(b):
        return bool(pd.isna(a) and pd.isna(b))
    return abs(a - b) <= eps


def _sort_key(vec: tuple) -> tuple:
    return tuple((bool(pd.isna(v)), 0.0 if pd.isna(v) else v) for v in vec)


def _bag_match(
    gt_df: pd.DataFrame, llm_df: pd.DataFrame,
    num_cols: list, other_cols: list, eps: float,
) -> int:
    """Count matching rows under bag semantics: exact on non-numeric columns,
    within-eps on numeric ones."""
    def by_key(df: pd.DataFrame) -> dict[tuple, list[tuple]]:
        groups: dict[tuple, list[tuple]] = {}
        for _, row in df.iterrows():
            key = tuple(str(row[c]) for c in other_cols)
            groups.setdefault(key, []).append(tuple(row[c] for c in num_cols))
        return groups

    llm_groups = by_key(llm_df)
    matched = 0
    for key, gt_vecs in by_key(gt_df).items():
        llm_vecs = llm_groups.get(key, [])
        # ponytail: sorted greedy is provably optimal in 1-D (the common case
        # here, since int/exact key columns are excluded from num_cols above)
        # but not for multi-column float vectors, where it can strand a
        # matchable pair. Upgrade to scipy.optimize.linear_sum_assignment
        # (Hungarian algorithm) if multi-column near-ties start costing
        # real matches.
        sorted_gt_vecs = sorted(gt_vecs, key=_sort_key)
        sorted_llm_vecs = sorted(llm_vecs, key=_sort_key)
        # Greedy matching: pair each gt vector with first available matching llm vector
        llm_used = [False] * len(sorted_llm_vecs)
        for a in sorted_gt_vecs:
            for j, b in enumerate(sorted_llm_vecs):
                if not llm_used[j] and all(_num_eq(x, y, eps) for x, y in zip(a, b)):
                    llm_used[j] = True
                    matched += 1
                    break
    return matched


def _result_set_comparison(
    gt_csv: Path, llm_csv: Path, ref_sql: str = "", eps: float = BENCHMARK_FLOAT_EPSILON,
) -> tuple[str, float | None, float | None, float | None, str | None]:
    error_file = llm_csv.with_suffix(".error")
    if error_file.exists():
        return "exec_error", 0.0, 0.0, 0.0, error_file.read_text().strip()

    if not llm_csv.exists():
        return "missing", None, None, None, None

    gt_df = pd.read_csv(gt_csv)
    llm_df = pd.read_csv(llm_csv)

    if len(gt_df) == 0 and len(llm_df) == 0:
        return "ok", 1.0, 1.0, 1.0, None

    if len(gt_df.columns) != len(llm_df.columns):
        return "ok", 0.0, 0.0, 0.0, None

    llm_df = _align_columns(gt_df, llm_df)

    num_cols = [
        c for c in gt_df.columns
        if gt_df[c].dtype.kind in "if" and llm_df[c].dtype.kind in "if"
        and not (gt_df[c].dtype.kind == "i" and llm_df[c].dtype.kind == "i")
    ]
    other_cols = [c for c in gt_df.columns if c not in num_cols]

    if _has_top_level_order_limit(ref_sql):
        min_len = min(len(gt_df), len(llm_df))
        matches = sum(
            1 for i in range(min_len)
            if all(_num_eq(gt_df[c].iat[i], llm_df[c].iat[i], eps) for c in num_cols)
            and all(str(gt_df[c].iat[i]) == str(llm_df[c].iat[i]) for c in other_cols)
        )
        precision = matches / len(llm_df) if len(llm_df) > 0 else 0.0
        recall = matches / len(gt_df) if len(gt_df) > 0 else 0.0
    else:
        matched = _bag_match(gt_df, llm_df, num_cols, other_cols, eps)
        precision = matched / len(llm_df) if len(llm_df) > 0 else 0.0
        recall = matched / len(gt_df) if len(gt_df) > 0 else 0.0

    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return "ok", precision, recall, f1, None


@lru_cache(maxsize=1)
def _tpch_schema() -> dict:
    """Parse the TPC-H DDL into a {table: {column: type}} mapping for the optimizer."""
    # ponytail: cwd-relative like benchmarking.py's schema_file default;
    # container cwd is /app, pytest cwd is app/ (hence the parent fallback)
    ddl_path = Path("benchmark/.tpch/schema.sql")
    if not ddl_path.exists():
        ddl_path = Path("../benchmark/.tpch/schema.sql")
    schema: dict[str, dict[str, str]] = {}
    for stmt in sqlglot.parse(ddl_path.read_text(), dialect="postgres"):
        if isinstance(stmt, exp.Create) and isinstance(stmt.this, exp.Schema):
            schema[stmt.this.this.name.lower()] = {
                col.name.lower(): col.args["kind"].sql(dialect="postgres")
                for col in stmt.this.expressions
                if isinstance(col, exp.ColumnDef)
            }
    return schema


def _strip_aliases(tree: exp.Expression) -> exp.Expression:
    """Rename table aliases to their base table names (alias-removal step).

    ponytail: tables appearing more than once (self-joins) keep their aliases;
    renaming both sides to the table name would collide.
    """
    tables = list(tree.find_all(exp.Table))
    counts = Counter(t.name for t in tables)
    for table in tables:
        alias = table.args.get("alias")
        if alias and counts[table.name] == 1 and alias.name != table.name:
            old = alias.name
            for col in tree.find_all(exp.Column):
                if col.table == old:
                    col.set("table", table.this.copy())
            table.set("alias", exp.TableAlias(this=table.this.copy()))
    return tree


def _normalize(tree: exp.Expression) -> exp.Expression:
    """Best-effort canonicalization. Falls back to the raw tree per side so a
    canonicalizer failure never zeroes out a model's score."""
    try:
        return _strip_aliases(optimize(tree.copy(), schema=_tpch_schema(), dialect="postgres"))
    except Exception as e:
        logger.debug("AST normalization failed, using raw tree: %s", e)
        return tree


def _parse_pair(gt_sql: str, llm_sql: str) -> tuple | None:
    try:
        gt_tree = sqlglot.parse(gt_sql, dialect="postgres")[0]
        llm_tree = sqlglot.parse(llm_sql, dialect="postgres")[0]
    except Exception as e:
        logger.debug("Failed to parse SQL for AST similarity: %s", e)
        return None
    if gt_tree is None or llm_tree is None:
        return None
    return gt_tree, llm_tree


def _diff_score(gt_tree, llm_tree) -> float | None:
    try:
        changes = diff(gt_tree, llm_tree)
    except Exception as e:
        logger.debug("Failed to diff SQL ASTs: %s", e)
        return None
    kept = sum(1 for c in changes if isinstance(c, Keep))
    total = len(changes)
    return kept / total if total > 0 else 1.0


def _ast_similarity(gt_sql: str, llm_sql: str) -> float | None:
    trees = _parse_pair(gt_sql, llm_sql)
    if trees is None:
        return None
    return _diff_score(*trees)


def _ast_similarity_normalized(gt_sql: str, llm_sql: str) -> float | None:
    trees = _parse_pair(gt_sql, llm_sql)
    if trees is None:
        return None
    return _diff_score(_normalize(trees[0]), _normalize(trees[1]))
