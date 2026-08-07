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

from backend.core.config import BENCHMARK_FLOAT_EPSILON

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

    status, precision, recall, f1, error_detail = _result_set_comparison(gt_csv, llm_csv)

    execution_accuracy = _execution_accuracy(
        status, precision, recall, gt_csv, llm_csv, gt_sql_text,
    )

    error_category = None
    if status == "exec_error" and error_detail:
        error_category = _classify_error(llm_sql_text, error_detail)

    ast_sim = _ast_similarity(gt_sql_text, llm_sql_text)
    ast_sim_norm = _ast_similarity_normalized(gt_sql_text, llm_sql_text)

    return {
        "query_id": query_id,
        "status": status,
        "execution_accuracy": execution_accuracy,
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

    ref_sets = [set(ref_df.iloc[:, i].astype(str)) for i in range(n)]
    gen_sets = [set(gen_df.iloc[:, j].astype(str)) for j in range(n)]
    best = max(
        permutations(range(n)),
        key=lambda perm: sum(len(ref_sets[i] & gen_sets[j]) for i, j in enumerate(perm)),
    )
    return gen_df.iloc[:, list(best)].set_axis(ref_df.columns, axis=1)


def _order_spec(ref_sql: str) -> list[tuple[str, bool]] | None:
    """[(column_name, descending)] for a top-level ORDER BY, else None.

    Returns None when the reference has no ORDER BY, won't parse, or orders by
    something that isn't a plain column/alias — callers then skip the ordering
    check rather than penalising the model for a harness limitation.
    """
    if not ref_sql.strip():
        return None
    try:
        tree = sqlglot.parse_one(ref_sql, dialect="postgres")
    except Exception as e:
        logger.debug("Failed to parse reference SQL for ORDER BY spec: %s", e)
        return None
    order = tree.args.get("order")
    if order is None:
        return None

    spec = []
    for item in order.expressions:
        node = item.this
        name = node.name if isinstance(node, exp.Column) else node.alias_or_name
        if not name:
            logger.debug("ORDER BY key %r is not a plain column; skipping order check", node)
            return None
        spec.append((name, bool(item.args.get("desc"))))
    return spec or None


def _is_sorted_by(df: pd.DataFrame, spec: list[tuple[str, bool]]) -> bool:
    """Whether df's rows honour the ORDER BY spec. True when not checkable —
    callers must not penalise a model for a harness limitation.

    Rows tied on the key columns may appear in any order, which is exactly the
    freedom SQL leaves undetermined.
    """
    absent = [name for name, _ in spec if name not in df.columns]
    if absent:
        logger.warning("ORDER BY keys %s absent from result columns; skipping order check", absent)
        return True
    if len(df) < 2:
        return True

    names = [name for name, _ in spec]
    keys = df[names]
    # ponytail: pandas sorts NaN to one end for every column, while Postgres
    # puts NULLs last for ASC and first for DESC — not expressible in a single
    # na_position. No TPC-H reference orders by a nullable column, so skip the
    # check rather than emulate it. Revisit if a Spec B variant introduces one.
    if keys.isna().any().any():
        logger.warning("NULL present in ORDER BY key column(s) %s; skipping order check", names)
        return True

    # A stable sort leaves an already-sorted sequence's row order untouched,
    # ties included — so comparing the resulting index to the original one
    # is equivalent to comparing the reordered values, without doing so.
    sorted_index = keys.sort_values(
        by=names,
        ascending=[not desc for _, desc in spec],
        kind="mergesort",
    ).index
    return sorted_index.equals(keys.index)


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
        llm_used = [False] * len(sorted_llm_vecs)
        for a in sorted_gt_vecs:
            for j, b in enumerate(sorted_llm_vecs):
                if not llm_used[j] and all(_num_eq(x, y, eps) for x, y in zip(a, b)):
                    llm_used[j] = True
                    matched += 1
                    break
    return matched


def _result_set_comparison(
    gt_csv: Path, llm_csv: Path, eps: float = BENCHMARK_FLOAT_EPSILON,
) -> tuple[str, float | None, float | None, float | None, str | None]:
    error_file = llm_csv.with_suffix(".error")
    if error_file.exists():
        return "exec_error", 0.0, 0.0, 0.0, error_file.read_text().strip()

    if not llm_csv.exists():
        # Score 0, don't return None: _compute_stats drops None, which would
        # let a generation failure lift the model's own mean. The status string
        # keeps the failure mode distinguishable in per-query output.
        return "missing", 0.0, 0.0, 0.0, None

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

    # Bag semantics for every query: precision/recall/F1 are order-insensitive
    # diagnostics. The ordering requirement is enforced by _execution_accuracy.
    matched = _bag_match(gt_df, llm_df, num_cols, other_cols, eps)

    precision = matched / len(llm_df) if len(llm_df) > 0 else 0.0
    recall = matched / len(gt_df) if len(gt_df) > 0 else 0.0

    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return "ok", precision, recall, f1, None


def _execution_accuracy(
    status: str,
    precision: float | None,
    recall: float | None,
    gt_csv: Path,
    llm_csv: Path,
    ref_sql: str,
) -> int:
    """Binary correctness: exact multiset match plus the reference's row ordering.

    ponytail: a tie spanning a LIMIT boundary — where the model cuts a
    different tied row than the reference did — reads as EX=0 for a defensibly
    correct answer. Unreachable today: no TPC-H ground truth at SF1 has any tie
    at all (measured, all 18 ordered queries, max group size 1). Spec B will
    reject parameter variants whose ground truth ties across the LIMIT cut,
    which is cheaper than detecting it here.
    """
    if status != "ok" or precision != 1.0 or recall != 1.0:
        return 0

    spec = _order_spec(ref_sql)
    if spec is None:
        return 1

    gt_df = pd.read_csv(gt_csv)
    llm_df = _align_columns(gt_df, pd.read_csv(llm_csv))
    return int(_is_sorted_by(llm_df, spec))


@lru_cache(maxsize=1)
def _tpch_schema() -> dict:
    """Parse the TPC-H DDL into a {table: {column: type}} mapping for the optimizer."""
    # ponytail: cwd-relative like benchmarking.py's schema_file default;
    # container cwd is /app and pytest cwd is app/ (both hit tpch/ directly),
    # repo-root runs hit the app/ fallback
    ddl_path = Path("tpch/schema.sql")
    if not ddl_path.exists():
        ddl_path = Path("app/tpch/schema.sql")
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
        return (
            sqlglot.parse_one(gt_sql, dialect="postgres"),
            sqlglot.parse_one(llm_sql, dialect="postgres"),
        )
    except Exception as e:
        logger.debug("Failed to parse SQL for AST similarity: %s", e)
        return None


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
