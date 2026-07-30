# Similarity Metric Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace rigid float rounding with configurable epsilon matching, and add an always-on normalized AST similarity metric beside the raw one.

**Architecture:** All metric logic lives in `app/src/text2query/benchmark/similarity.py`; reporting surfaces in `app/src/text2query/benchmark/reporting.py` mostly iterate the `METRICS` tuple, so the new metric flows through automatically except four hardcoded tables. Normalization reuses `sqlglot.optimizer.optimize` with a schema parsed from `benchmark/.tpch/schema.sql`, plus a small alias-strip pass (verified against sqlglot 29: `optimize` sorts commutative predicates but keeps aliases).

**Tech Stack:** Python 3.12, pandas, sqlglot ≥ 26 (installed: 29), pytest via `uv`.

**Spec:** `docs/superpowers/specs/2026-07-30-similarity-improvements-design.md`

## Global Constraints

- No new dependencies; no file splits (`similarity.py` stays single-file).
- The only new env toggle is `BENCHMARK_FLOAT_EPSILON` (default `1e-4`, absolute tolerance).
- `ast_similarity_normalized` is always-on, never toggled.
- Normalization fallback is per side: if `optimize()` fails for one query, that side uses its raw tree; the column is `None` only when a query fails to parse (same condition as raw `ast_similarity`).
- Commit messages use the repo's conventional style (`feat:`, `test:`, `docs:`); **never add a Co-Authored-By trailer**.
- Run tests from `app/`: `cd app && uv run pytest tests/<file> -v`.

---

### Task 1: Epsilon-based float matching

**Files:**
- Modify: `app/src/text2query/core/config.py` (after line 35, `BENCHMARK_DATA_PATH`)
- Modify: `compose.yml.example` (benchmark env block, after `BENCHMARK_SCALE_FACTOR`)
- Modify: `app/src/text2query/benchmark/similarity.py` (`_result_set_comparison` and helpers)
- Test: `app/tests/test_similarity.py`

**Interfaces:**
- Consumes: existing `_result_set_comparison(gt_csv, llm_csv, ref_sql="") -> tuple[str, float|None, float|None, float|None, str|None]` and `_align_columns`.
- Produces: `_result_set_comparison` gains keyword `eps: float = BENCHMARK_FLOAT_EPSILON`; new module constant `text2query.core.config.BENCHMARK_FLOAT_EPSILON: float`. Return type unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `class TestResultSetComparison` in `app/tests/test_similarity.py`:

```python
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
```

Also rename the now-misleading `test_float_rounding_to_four_decimal_places` to `test_tiny_float_noise_within_epsilon` (body unchanged — 2e-8 < 1e-4 still matches).

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd app && uv run pytest tests/test_similarity.py -v`
Expected: `test_custom_epsilon_loosens_match` FAILS with `TypeError: _result_set_comparison() got an unexpected keyword argument 'eps'`; `test_epsilon_boundary_and_beyond` FAILS (old code rounds both to different 4-decimal values → prec 0.0, or equal → 1.0, not 0.5). Pre-existing tests PASS.

- [ ] **Step 3: Add the config constant and compose line**

In `app/src/text2query/core/config.py`, after the `BENCHMARK_DATA_PATH` line:

```python
BENCHMARK_FLOAT_EPSILON = _env("BENCHMARK_FLOAT_EPSILON", 1e-4, float)
```

In `compose.yml.example`, after the `BENCHMARK_SCALE_FACTOR` line:

```yaml
  BENCHMARK_FLOAT_EPSILON: "1e-4"           # Absolute float tolerance in result comparison; loosen to 1e-2 for money-heavy queries
```

- [ ] **Step 4: Implement epsilon matching in similarity.py**

In `app/src/text2query/benchmark/similarity.py`:

Keep `from collections import Counter` even though its bag-comparison use disappears here — Task 2 reuses it for alias counting. Add to imports:

```python
from text2query.core.config import BENCHMARK_FLOAT_EPSILON
```

Add helpers (above `_result_set_comparison`):

```python
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
        # ponytail: sort-then-zip pairing; switch to optimal assignment if
        # multi-float-column near-ties ever cost real matches
        for a, b in zip(sorted(gt_vecs, key=_sort_key), sorted(llm_vecs, key=_sort_key)):
            if all(_num_eq(x, y, eps) for x, y in zip(a, b)):
                matched += 1
    return matched
```

Change `_result_set_comparison`'s signature:

```python
def _result_set_comparison(
    gt_csv: Path, llm_csv: Path, ref_sql: str = "", eps: float = BENCHMARK_FLOAT_EPSILON,
) -> tuple[str, float | None, float | None, float | None, str | None]:
```

Replace everything from the `for df in (gt_df, llm_df):` rounding/fillna loop through the end of the bag-mode `else:` branch (currently the `round(4)`/`fillna` loop, the ordered `matches` computation, and the `Counter` intersection) with:

```python
    num_cols = [
        c for c in gt_df.columns
        if gt_df[c].dtype.kind in "if" and llm_df[c].dtype.kind in "if"
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
```

The trailing `f1 = ...` line and `return` stay unchanged. The `for df in (...)` rounding loop and `df.fillna("NULL", ...)` are deleted entirely (non-numeric NaN renders as `str(nan) == "nan"` consistently on both sides).

- [ ] **Step 5: Run the full similarity test file**

Run: `cd app && uv run pytest tests/test_similarity.py -v`
Expected: ALL PASS (including pre-existing `test_column_reorder_alignment`, `test_both_empty_result_sets`, ordered-mode tests).

- [ ] **Step 6: Commit**

```bash
git add app/src/text2query/core/config.py compose.yml.example \
        app/src/text2query/benchmark/similarity.py app/tests/test_similarity.py
git commit -m "feat: epsilon-based float matching in result-set comparison"
```

---

### Task 2: Normalized AST similarity

**Files:**
- Modify: `app/src/text2query/benchmark/similarity.py` (refactor `_ast_similarity`, add normalization; extend `evaluate_query` return dict)
- Test: `app/tests/test_similarity.py`

**Interfaces:**
- Consumes: existing `_ast_similarity(gt_sql, llm_sql) -> float | None`; `sqlglot.optimizer.optimize`; DDL at `benchmark/.tpch/schema.sql` (cwd `/app` in the container, `app/` under pytest — hence the parent-dir fallback below).
- Produces: `_ast_similarity_normalized(gt_sql: str, llm_sql: str) -> float | None`; `evaluate_query` result dict gains key `"ast_similarity_normalized": float | None` (after `"ast_similarity"`). `_ast_similarity`'s signature and semantics are unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `app/tests/test_similarity.py` (import `_ast_similarity_normalized` and `_tpch_schema` alongside the existing imports):

```python
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
        # both aliases reference the same table; stripping would collide, so
        # identical self-joins must still score 1.0
        sql = (
            "SELECT a.l_orderkey FROM lineitem AS a "
            "JOIN lineitem AS b ON a.l_orderkey = b.l_orderkey"
        )
        assert _ast_similarity_normalized(sql, sql) == 1.0

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && uv run pytest tests/test_similarity.py -v`
Expected: `ImportError: cannot import name '_ast_similarity_normalized'`.

- [ ] **Step 3: Implement normalization**

In `app/src/text2query/benchmark/similarity.py`, extend imports:

```python
from collections import Counter
from functools import lru_cache

from sqlglot import exp
from sqlglot.optimizer import optimize
```

Add (near `_ast_similarity`):

```python
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
```

Refactor the existing `_ast_similarity` into shared helpers plus the two public scorers (replaces the current `_ast_similarity` body entirely):

```python
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
```

In `evaluate_query`, after the `ast_sim = _ast_similarity(...)` line add:

```python
    ast_sim_norm = _ast_similarity_normalized(gt_sql_text, llm_sql_text)
```

and in the returned dict, after `"ast_similarity": _round(ast_sim),`:

```python
        "ast_similarity_normalized": _round(ast_sim_norm),
```

- [ ] **Step 4: Run the full similarity test file**

Run: `cd app && uv run pytest tests/test_similarity.py -v`
Expected: ALL PASS, including the pre-existing `TestAstSimilarity` class (raw scorer behavior unchanged: `test_predicate_reorder_scores_high` still expects raw > 0.8 but < 1.0 semantics, `test_between_vs_dual_inequality` unchanged).

- [ ] **Step 5: Commit**

```bash
git add app/src/text2query/benchmark/similarity.py app/tests/test_similarity.py
git commit -m "feat: always-on normalized AST similarity metric"
```

---

### Task 3: Reporting integration

**Files:**
- Modify: `app/src/text2query/benchmark/reporting.py` (constants + four hardcoded tables)
- Test: `app/tests/test_reporting.py`

**Interfaces:**
- Consumes: `evaluate_query` result dicts now containing `"ast_similarity_normalized"` (Task 2).
- Produces: `METRICS == ("result_f1", "ast_similarity", "ast_similarity_normalized")`; `CSV_FIELDNAMES` gains `"ast_similarity_normalized"` after `"ast_similarity"`. All aggregation loops (`generate_reports` per-query agg, `generate_cross_model_report`, `_aggregate_model_results`, single-model `format_run_summary`) iterate `METRICS` and update automatically.

- [ ] **Step 1: Update the failing constants test first**

In `app/tests/test_reporting.py` replace `test_metrics_constant_has_matching_labels`:

```python
def test_metrics_constant_has_matching_labels():
    assert METRICS == ("result_f1", "ast_similarity", "ast_similarity_normalized")
    assert METRIC_LABELS == {
        "result_f1": "Result F1",
        "ast_similarity": "AST similarity",
        "ast_similarity_normalized": "AST similarity (normalized)",
    }
    assert set(METRICS) == set(METRIC_LABELS)
```

And in the session-header test, replace the Metrics assertion:

```python
    assert _field("Metrics", "Result F1, AST similarity, AST similarity (normalized)") in header
```

- [ ] **Step 2: Run reporting tests to verify they fail**

Run: `cd app && uv run pytest tests/test_reporting.py -v`
Expected: `test_metrics_constant_has_matching_labels` and the session-header test FAIL on the old constants.

- [ ] **Step 3: Update reporting.py**

Constants:

```python
CSV_FIELDNAMES = [
    "seed", "model", "query_id", "nl_query", "prompt",
    "generated_sql", "real_sql", "status",
    "result_precision", "result_recall", "result_f1",
    "ast_similarity", "ast_similarity_normalized", "error_category",
]

METRICS = ("result_f1", "ast_similarity", "ast_similarity_normalized")
METRIC_LABELS = {
    "result_f1": "Result F1",
    "ast_similarity": "AST similarity",
    "ast_similarity_normalized": "AST similarity (normalized)",
}
```

`_format_per_query` — per-seed table gains a column, and the stats loop derives from `METRICS` instead of a hardcoded list:

```python
    lines = [
        "## Per-Seed Results\n",
        "| Seed | Status | Result F1 | AST Sim | AST Sim (norm) |",
        "|---|---|---|---|---|",
    ]

    for r in seed_results:
        lines.append(
            f"| {r['seed']} | {r['status']} | {_v(r['result_f1'])} "
            f"| {_v(r['ast_similarity'])} | {_v(r.get('ast_similarity_normalized'))} |"
        )
```

and:

```python
    for metric in METRICS:
        label = METRIC_LABELS[metric]
        stats = _compute_stats([r.get(metric) for r in seed_results])
```

(the loop body below the old `for label, metric in [...]` line is unchanged).

`_format_summary` — add the normalized column:

```python
    lines = [
        "| Query | Seeds ok | F1 (mean±std) | AST (mean±std) | AST norm (mean±std) | F1 95% CI |",
        "|---|---|---|---|---|---|",
    ]
```

and inside the loop, after the `ast_str` line:

```python
        norm = q["ast_similarity_normalized"]
        norm_str = f"{norm['mean']:.4f} ± {norm['std']:.4f}" if norm["mean"] is not None else "—"
```

with the row line becoming:

```python
        lines.append(f"| {qid} | {ok_count}/{num_seeds} | {f1_str} | {ast_str} | {norm_str} | {ci_str} |")
```

`generate_cross_model_report` — extend the sections list:

```python
    for title, metric, show_status in [
        ("F1", "result_f1", True),
        ("AST Similarity", "ast_similarity", False),
        ("AST Similarity (normalized)", "ast_similarity_normalized", False),
    ]:
```

`format_run_summary` multi-model table — widen header and row:

```python
        lines.append(
            f"  {'Model':<{name_width}}   {'Result F1':>9}   {'AST sim':>7}   {'AST norm':>8}   {'Exact':>7}   {'Fail':>4}"
        )
        for model in models:
            agg = aggregates[model]
            f1 = agg["metrics"]["result_f1"]["mean"]
            ast = agg["metrics"]["ast_similarity"]["mean"]
            norm = agg["metrics"]["ast_similarity_normalized"]["mean"]
            f1_str = f"{f1:.4f}" if f1 is not None else "—"
            ast_str = f"{ast:.4f}" if ast is not None else "—"
            norm_str = f"{norm:.4f}" if norm is not None else "—"
            exact_str = f"{agg['exact_matches']} / {agg['total_queries']}"
            lines.append(
                f"  {model:<{name_width}}   {f1_str:>9}   {ast_str:>7}   {norm_str:>8}   {exact_str:>7}   {agg['failures']:>4}"
            )
```

(single-model branch already iterates `METRICS` — no change.)

- [ ] **Step 4: Run both test files**

Run: `cd app && uv run pytest tests/test_reporting.py tests/test_similarity.py -v`
Expected: ALL PASS. Old fixture dicts without the new key keep working because every aggregation uses `r.get(metric)` (yielding mean `None` → rendered as `—`); `test_results_csv_single_seed` passes because `evaluate_query` now emits the key end-to-end.

- [ ] **Step 5: Run the whole suite**

Run: `cd app && uv run pytest -q`
Expected: ALL PASS (catches any consumer of `METRICS`/`CSV_FIELDNAMES` not covered above, e.g. `test_multi_seed.py`).

- [ ] **Step 6: Commit**

```bash
git add app/src/text2query/benchmark/reporting.py app/tests/test_reporting.py
git commit -m "feat: report normalized AST similarity across all surfaces"
```
