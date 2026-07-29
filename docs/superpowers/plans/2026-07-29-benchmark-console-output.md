# Benchmark Console Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a session header to `docker compose --profile benchmark up` output that states what's being benchmarked (model, dataset, metrics, prompt features, LLM params), and rewrite the closing summary to report results instead of restating config — while removing the nine redundancy patterns catalogued in the spec.

**Architecture:** Two new pure formatting functions in `reporting.py` — `format_session_header()` (printed once, before any stage runs) and a rewritten `format_run_summary()` (printed once, at the very end, now built from actual scores via a new `_aggregate_model_results()` helper). Both share a `_field()` label/value formatter so the whole session reads as one visually consistent column. Stage-transition banners get a matching `_banner()` helper local to `benchmarking.py`. Everywhere else, this plan deletes: duplicated stage titles, per-model name repeats, single-seed markers, paths that go stale after archiving, archive-bookkeeping prints, and a cleartext `DATABASE_URL` in the old summary.

**Tech Stack:** Python 3.12, pytest. No new dependencies — `textwrap` and `time` are stdlib.

## Global Constraints

- All full-width dividers (header, footer, per-model banner) are exactly 60 columns, using `═`. Stage banners use `─`, also padded to 60 columns. (Spec: "Placement" and stage-banner examples.)
- `METRICS = ("result_f1", "ast_similarity")` is the single source of truth for which metrics are scored and labeled — both the header's `Metrics` line and the aggregation logic must read from it, not a separate literal. (Spec section 2.)
- The database URL must never appear unredacted in console output. It appears exactly once, in the header, through the existing `_redact_db_url()`. (Spec finding #9.)
- Terminal output only — scoring, archiving, and the written `.md`/`.csv`/`.json` artifacts are unchanged. (Spec "Scope".)

---

### Task 1: Shared metrics constant

**Files:**
- Modify: `app/src/text2query/benchmark/reporting.py:140` (inside `generate_reports`), `app/src/text2query/benchmark/reporting.py:249-251` (inside `generate_cross_model_report`)
- Test: `app/tests/test_reporting.py`

**Interfaces:**
- Produces: `METRICS: tuple[str, ...]` and `METRIC_LABELS: dict[str, str]`, both module-level in `reporting.py`. Every later task in this plan reads these instead of a local literal.

- [ ] **Step 1: Write the failing test**

Add to `app/tests/test_reporting.py` (alongside the existing imports at the top):

```python
from text2query.benchmark.reporting import (
    _compute_stats, generate_reports, format_run_summary,
    METRICS, METRIC_LABELS,
)


def test_metrics_constant_has_matching_labels():
    assert METRICS == ("result_f1", "ast_similarity")
    assert METRIC_LABELS == {"result_f1": "Result F1", "ast_similarity": "AST similarity"}
    assert set(METRICS) == set(METRIC_LABELS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && .venv/bin/pytest tests/test_reporting.py::test_metrics_constant_has_matching_labels -v`
Expected: FAIL with `ImportError: cannot import name 'METRICS'`

- [ ] **Step 3: Add the constants and use them in place of the two local lists**

In `app/src/text2query/benchmark/reporting.py`, add right after `CSV_FIELDNAMES` (currently ends at line 22):

```python
METRICS = ("result_f1", "ast_similarity")
METRIC_LABELS = {"result_f1": "Result F1", "ast_similarity": "AST similarity"}
```

In `generate_reports`, replace:

```python
    metrics_to_aggregate = ["result_f1", "ast_similarity"]
```

with nothing (delete the line), and change the loop that used it:

```python
        for metric in metrics_to_aggregate:
```

to:

```python
        for metric in METRICS:
```

In `generate_cross_model_report`, replace:

```python
    metrics_to_aggregate = [
        "result_f1", "ast_similarity",
    ]
```

with nothing (delete), and change:

```python
            for metric in metrics_to_aggregate:
```

to:

```python
            for metric in METRICS:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && .venv/bin/pytest tests/test_reporting.py -v`
Expected: All PASS, including the existing `test_results_csv_single_seed` (regression check — `generate_reports` still works with `METRICS` in place of the deleted local list).

- [ ] **Step 5: Commit**

```bash
cd app && git add src/text2query/benchmark/reporting.py tests/test_reporting.py
git commit -m "refactor: share METRICS constant between report generation and (upcoming) session header"
```

---

### Task 2: Session header

**Files:**
- Modify: `app/src/text2query/benchmark/reporting.py` (add near the top, after `CSV_FIELDNAMES`/`METRICS`)
- Test: `app/tests/test_reporting.py`

**Interfaces:**
- Consumes: `METRICS`, `METRIC_LABELS` (Task 1), `_redact_db_url` (already exists at `reporting.py:360`).
- Produces:
  - `_field(label: str, value: str) -> str` — one aligned `"  Label            value"` row, wrapping long values under the label column.
  - `_plural(n: int, singular: str, plural: str | None = None) -> str`
  - `format_session_header(*, scale_factor: int, models: list[str], total_available: int, query_ids: list[str] | None, num_seeds: int, temperature: float, max_tokens: int, num_ctx: int, prompt_flags: dict, database_url: str) -> str`

  These three names are consumed by Task 3 (`_field`, `_plural`) and Task 6 (`format_session_header`).

- [ ] **Step 1: Write the failing tests**

Add to `app/tests/test_reporting.py`:

```python
from text2query.benchmark.reporting import (
    _compute_stats, generate_reports, format_run_summary,
    METRICS, METRIC_LABELS, _field, format_session_header,
)


def test_field_pads_label_and_wraps_long_values():
    row = _field("Model", "qwen2.5-coder:7b")
    assert row == "  Model             qwen2.5-coder:7b"

    wrapped = _field("Prompt features", "a, " * 40 + "z")
    lines = wrapped.split("\n")
    assert len(lines) > 1
    assert lines[0].startswith("  Prompt features  ")
    # continuation lines line up under the value column, not the label
    assert lines[1].startswith(" " * 20)


def test_format_session_header_single_model_filtered_queries():
    header = format_session_header(
        scale_factor=1, models=["qwen2.5-coder:7b"], total_available=22,
        query_ids=["01", "07", "16"], num_seeds=1,
        temperature=0.1, max_tokens=2048, num_ctx=4096,
        prompt_flags={"schema_ddl": True, "few_shot": 1, "planning": False},
        database_url="postgresql://user:password@postgres:5432/testdb",
    )
    assert "TPC-H (scale factor 1)" in header
    assert _field("Model", "qwen2.5-coder:7b") in header
    assert _field("Queries", "3 of 22 (01, 07, 16)") in header
    assert _field("Seeds", "1") in header
    assert _field("Evaluations", "3  (3 queries × 1 seed × 1 model)") in header
    assert _field("Metrics", "Result F1, AST similarity") in header
    assert "schema_ddl, few_shot=1" in header
    assert "planning" not in header  # False flags are omitted, not printed as planning=False
    assert "password" not in header
    assert _field("Database", "postgresql://***:***@postgres:5432/testdb") in header


def test_format_session_header_multi_model_all_queries_no_flags():
    header = format_session_header(
        scale_factor=1, models=["m1", "m2"], total_available=22,
        query_ids=None, num_seeds=3,
        temperature=0.1, max_tokens=2048, num_ctx=4096,
        prompt_flags={}, database_url="postgresql://u:p@host/db",
    )
    assert _field("Models", "m1, m2") in header
    assert _field("Queries", "22 of 22 (all)") in header
    assert _field("Evaluations", "132  (22 queries × 3 seeds × 2 models)") in header
    assert _field("Prompt features", "none (baseline)") in header
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && .venv/bin/pytest tests/test_reporting.py -k "field or session_header" -v`
Expected: FAIL with `ImportError: cannot import name '_field'`

- [ ] **Step 3: Implement `_field`, `_plural`, and `format_session_header`**

Add `import textwrap` to the top of `app/src/text2query/benchmark/reporting.py` (alongside the existing `import csv`, `import json`, etc.).

Add, right after the `METRIC_LABELS` constant from Task 1:

```python
_LABEL_WIDTH = 18


def _field(label: str, value: str) -> str:
    """Render one aligned 'Label   value' row, wrapping long values under the value column."""
    indent = " " * (2 + _LABEL_WIDTH)
    wrapped = textwrap.wrap(value, width=78 - len(indent)) or [""]
    rows = [f"  {label:<{_LABEL_WIDTH}}{wrapped[0]}"]
    rows.extend(f"{indent}{cont}" for cont in wrapped[1:])
    return "\n".join(rows)


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return singular if n == 1 else (plural or f"{singular}s")
```

Add `format_session_header`, right after `_plural`:

```python
def format_session_header(
    *,
    scale_factor: int,
    models: list[str],
    total_available: int,
    query_ids: list[str] | None,
    num_seeds: int,
    temperature: float,
    max_tokens: int,
    num_ctx: int,
    prompt_flags: dict,
    database_url: str,
) -> str:
    """Render the session header: what's being benchmarked, and how, printed once up front."""
    rule = "═" * 60
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        rule,
        f"  text2query Benchmark · TPC-H (scale factor {scale_factor})",
        f"  {timestamp}",
        rule,
    ]

    model_label = "Models" if len(models) > 1 else "Model"
    lines.append(_field(model_label, ", ".join(models)))

    if query_ids is None:
        queries_value = f"{total_available} of {total_available} (all)"
    else:
        queries_value = f"{len(query_ids)} of {total_available} ({', '.join(query_ids)})"
    lines.append(_field("Queries", queries_value))

    lines.append(_field("Seeds", str(num_seeds)))

    benchmarked_count = len(query_ids) if query_ids else total_available
    total_evals = benchmarked_count * num_seeds * len(models)
    lines.append(_field(
        "Evaluations",
        f"{total_evals}  ({benchmarked_count} {_plural(benchmarked_count, 'query', 'queries')} "
        f"× {num_seeds} {_plural(num_seeds, 'seed')} × {len(models)} {_plural(len(models), 'model')})",
    ))

    lines.append(_field("Metrics", ", ".join(METRIC_LABELS[m] for m in METRICS)))

    enabled = [(k if isinstance(v, bool) else f"{k}={v}") for k, v in prompt_flags.items() if v]
    lines.append(_field("Prompt features", ", ".join(enabled) if enabled else "none (baseline)"))

    lines.append(_field("LLM params", f"temp={temperature}, max_tokens={max_tokens}, num_ctx={num_ctx}"))

    lines.append(_field("Database", _redact_db_url(database_url)))

    lines.append(rule)
    return "\n".join(lines) + "\n"
```

`_redact_db_url` is defined later in the file (`reporting.py:360` in the current version) — Python resolves the call at call-time, not definition-time, so the forward reference is fine; no reordering needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && .venv/bin/pytest tests/test_reporting.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
cd app && git add src/text2query/benchmark/reporting.py tests/test_reporting.py
git commit -m "feat: add benchmark session header (model, dataset, metrics, prompt features)"
```

---

### Task 3: Rewrite the closing summary to report scores

**Files:**
- Modify: `app/src/text2query/benchmark/reporting.py:401-446` (replaces the existing `format_run_summary`)
- Test: `app/tests/test_reporting.py:78-101` (replaces the two existing tests, which assert on the old config-based signature)

**Interfaces:**
- Consumes: `METRICS`, `METRIC_LABELS`, `_field`, `_plural` (Task 1, 2), `_compute_stats` (already exists at `reporting.py:44`).
- Produces:
  - `_aggregate_model_results(rows: list[dict]) -> dict` with keys `metrics` (dict of `_compute_stats` results per metric), `exact_matches: int`, `total_queries: int`, `failures: int`, `num_seeds: int`.
  - `_format_elapsed(seconds: float) -> str`
  - `format_run_summary(precomputed: dict[str, list[dict]], models: list[str], session_dir: Path, elapsed: float) -> str` — **signature change** from the old `(total_questions, total_ground_truth, query_ids, models, num_seeds, session_dir, database_url, prompt_flags)`. Task 6 is the only other caller and gets updated to match.

- [ ] **Step 1: Write the failing tests**

In `app/tests/test_reporting.py`, delete the two existing tests (`test_format_run_summary_single_model_all_queries` and `test_format_run_summary_multi_model_filtered_queries`, currently lines 78-101) and replace with:

```python
def test_aggregate_model_results_counts_exact_matches_and_failures():
    rows = [
        {"query_id": 1, "seed": 1, "status": "ok", "result_f1": 1.0, "ast_similarity": 0.9},
        {"query_id": 2, "seed": 1, "status": "ok", "result_f1": 0.5, "ast_similarity": 0.7},
        {"query_id": 3, "seed": 1, "status": "exec_error", "result_f1": 0.0, "ast_similarity": 0.0},
    ]
    agg = _aggregate_model_results(rows)
    assert agg["exact_matches"] == 1
    assert agg["total_queries"] == 3
    assert agg["failures"] == 1
    assert agg["num_seeds"] == 1


def test_aggregate_model_results_exact_match_requires_perfect_mean_across_seeds():
    rows = [
        {"query_id": 1, "seed": 1, "status": "ok", "result_f1": 1.0, "ast_similarity": 0.9},
        {"query_id": 1, "seed": 2, "status": "ok", "result_f1": 0.8, "ast_similarity": 0.9},
    ]
    agg = _aggregate_model_results(rows)
    assert agg["exact_matches"] == 0  # mean F1 across the two seeds is 0.9, not 1.0
    assert agg["total_queries"] == 1
    assert agg["num_seeds"] == 2


def test_format_elapsed():
    assert _format_elapsed(252) == "4m 12s"
    assert _format_elapsed(5) == "0m 5s"


def test_format_run_summary_single_model():
    precomputed = {
        "m1": [
            {"query_id": 1, "seed": 1, "status": "ok", "result_f1": 1.0, "ast_similarity": 0.9},
            {"query_id": 2, "seed": 1, "status": "ok", "result_f1": 0.5, "ast_similarity": 0.7},
            {"query_id": 3, "seed": 1, "status": "exec_error", "result_f1": 0.0, "ast_similarity": 0.0},
        ]
    }
    summary = format_run_summary(precomputed, ["m1"], Path("benchmark/results/x"), elapsed=252.0)
    assert "elapsed 4m 12s" in summary
    assert _field("Exact matches", "1 / 3") in summary
    assert _field("Failures", "1") in summary
    assert _field("Session", "benchmark/results/x") in summary
    assert "password" not in summary
    assert "postgresql" not in summary


def test_format_run_summary_multi_model_shows_per_model_row():
    precomputed = {
        "m1": [{"query_id": 1, "seed": 1, "status": "ok", "result_f1": 1.0, "ast_similarity": 0.9}],
        "m2": [{"query_id": 1, "seed": 1, "status": "ok", "result_f1": 0.5, "ast_similarity": 0.7}],
    }
    summary = format_run_summary(precomputed, ["m1", "m2"], Path("benchmark/results/x"), elapsed=5.0)
    assert "m1" in summary
    assert "m2" in summary
    assert "0.5000" in summary
    assert _field("Session", "benchmark/results/x") in summary
```

Update the import at the top of the file to include the new names:

```python
from text2query.benchmark.reporting import (
    _compute_stats, generate_reports, format_run_summary,
    METRICS, METRIC_LABELS, _field, format_session_header,
    _aggregate_model_results, _format_elapsed,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && .venv/bin/pytest tests/test_reporting.py -k "aggregate or elapsed or run_summary" -v`
Expected: FAIL with `ImportError: cannot import name '_aggregate_model_results'`

- [ ] **Step 3: Replace `format_run_summary`**

In `app/src/text2query/benchmark/reporting.py`, delete the entire existing `format_run_summary` function (currently lines 401-446, from `def format_run_summary(` through the final `return "\n".join(lines) + "\n"`), and replace it with:

```python
def _aggregate_model_results(rows: list[dict]) -> dict:
    """Aggregate one model's flat per-(query, seed) results into summary stats."""
    by_query: dict[int, list[dict]] = {}
    for r in rows:
        by_query.setdefault(r["query_id"], []).append(r)

    metrics = {metric: _compute_stats([r.get(metric) for r in rows]) for metric in METRICS}

    exact_matches = 0
    for qid_rows in by_query.values():
        qid_f1 = _compute_stats([r.get("result_f1") for r in qid_rows])
        if qid_f1["mean"] == 1.0:
            exact_matches += 1

    failures = sum(1 for r in rows if r["status"] != "ok")

    return {
        "metrics": metrics,
        "exact_matches": exact_matches,
        "total_queries": len(by_query),
        "failures": failures,
        "num_seeds": len(rows) // len(by_query) if by_query else 0,
    }


def _format_elapsed(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs}s"


def format_run_summary(
    precomputed: dict[str, list[dict]],
    models: list[str],
    session_dir: Path,
    elapsed: float,
) -> str:
    """Render the closing 'Benchmark Complete' block: aggregate scores, not restated config."""
    rule = "═" * 60
    lines = [rule, f"  Benchmark Complete  ·  elapsed {_format_elapsed(elapsed)}", rule]

    aggregates = {model: _aggregate_model_results(precomputed[model]) for model in models}

    if len(models) == 1:
        agg = aggregates[models[0]]
        for i, metric in enumerate(METRICS):
            stats = agg["metrics"][metric]
            value = f"{stats['mean']:.4f}" if stats["mean"] is not None else "—"
            if i == 0:
                value += (
                    f"   (mean over {agg['total_queries']} "
                    f"{_plural(agg['total_queries'], 'query', 'queries')} × "
                    f"{agg['num_seeds']} {_plural(agg['num_seeds'], 'seed')})"
                )
            lines.append(_field(METRIC_LABELS[metric], value))
        lines.append(_field("Exact matches", f"{agg['exact_matches']} / {agg['total_queries']}"))
        lines.append(_field("Failures", str(agg["failures"])))
    else:
        name_width = max(len("Model"), max(len(m) for m in models))
        lines.append(
            f"  {'Model':<{name_width}}   {'Result F1':>9}   {'AST sim':>7}   {'Exact':>7}   {'Fail':>4}"
        )
        for model in models:
            agg = aggregates[model]
            f1 = agg["metrics"]["result_f1"]["mean"]
            ast = agg["metrics"]["ast_similarity"]["mean"]
            f1_str = f"{f1:.4f}" if f1 is not None else "—"
            ast_str = f"{ast:.4f}" if ast is not None else "—"
            exact_str = f"{agg['exact_matches']} / {agg['total_queries']}"
            lines.append(
                f"  {model:<{name_width}}   {f1_str:>9}   {ast_str:>7}   {exact_str:>7}   {agg['failures']:>4}"
            )

    lines.append("")
    lines.append(_field("Session", str(session_dir)))
    lines.append(rule)
    return "\n".join(lines) + "\n"
```

Note: `_compute_stats([])["mean"]` is `None`, and `None == 1.0` is `False`, so a query with zero rows never counts as an exact match — no extra guard needed for the empty case beyond what's already there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && .venv/bin/pytest tests/test_reporting.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
cd app && git add src/text2query/benchmark/reporting.py tests/test_reporting.py
git commit -m "feat: rewrite benchmark closing summary to report scores instead of config"
```

---

### Task 4: Remove archive bookkeeping and stale-path prints

**Files:**
- Modify: `app/src/text2query/benchmark/reporting.py` — `_write_results_csv` (line 35), `generate_reports` (line 227), `generate_cross_model_report` (line 314), `_move_contents` (lines 348-357), `archive_session` (lines 338, 344), `write_session_manifest` (line 397)

**Interfaces:**
- No signature changes except `_move_contents`, whose unused `label` parameter is dropped once its only use (the print) is removed. Both call sites (inside `archive_session`) are updated in the same step.

- [ ] **Step 1: Confirm no test asserts on the strings being removed**

Run: `cd app && grep -rn "Moved reports\|Session archived\|Session manifest\|Reports generated\|CSV export\|Comparison report\|Moved.*dirs of" tests/`
Expected: no output. (Already verified during design — this step is a guard against having missed a caller before editing.)

- [ ] **Step 2: Remove the prints**

In `app/src/text2query/benchmark/reporting.py`:

In `_write_results_csv`, change:
```python
    print(f"  CSV export -> {csv_path} ({len(results)} rows)")
```
to:
```python
    print(f"  CSV export ({len(results)} rows)")
```

In `generate_reports`, delete this line entirely (the per-query `"  [{qid}] evaluated across..."` lines immediately above it already show progress):
```python
    print(f"  Reports generated -> {report_dir}")
```

In `generate_cross_model_report`, change:
```python
    print(f"  Comparison report -> {comparison_path}")
```
to:
```python
    print("  Comparison report generated")
```

Replace `_move_contents` (currently):
```python
def _move_contents(src_dir: Path, dst_dir: Path, label: str) -> None:
    """Move a directory's subdirectories (model dirs, seed dirs, or nested layouts) to dst."""
    if not src_dir.exists():
        return

    subdirs = sorted(d for d in src_dir.iterdir() if d.is_dir())
    for sd in subdirs:
        shutil.move(str(sd), str(dst_dir))
    if subdirs:
        print(f"  Moved {len(subdirs)} dirs of {label} -> {dst_dir}")
```
with:
```python
def _move_contents(src_dir: Path, dst_dir: Path) -> None:
    """Move a directory's subdirectories (model dirs, seed dirs, or nested layouts) to dst."""
    if not src_dir.exists():
        return

    subdirs = sorted(d for d in src_dir.iterdir() if d.is_dir())
    for sd in subdirs:
        shutil.move(str(sd), str(dst_dir))
```

In `archive_session`, update the two call sites and delete the two prints. Change:
```python
    _move_contents(queries_dir, session_queries, "queries")
    _move_contents(answers_dir, session_answers, "answers")

    if report_dir.exists():
        shutil.move(str(report_dir), str(session_report))
        print(f"  Moved reports -> {session_report}")

    for d in [queries_dir, answers_dir]:
        if d.exists():
            shutil.rmtree(str(d))

    print(f"  Session archived -> {session_dir}")
    return session_dir
```
to:
```python
    _move_contents(queries_dir, session_queries)
    _move_contents(answers_dir, session_answers)

    if report_dir.exists():
        shutil.move(str(report_dir), str(session_report))

    for d in [queries_dir, answers_dir]:
        if d.exists():
            shutil.rmtree(str(d))

    return session_dir
```

In `write_session_manifest`, delete:
```python
    print(f"  Session manifest -> {manifest_path}")
```
(keep the `return manifest_path` immediately after it).

- [ ] **Step 3: Run the full test suite to confirm no regression**

Run: `cd app && .venv/bin/pytest tests/ -v`
Expected: All PASS — `test_archive_with_seed_subdirs` (`test_multi_seed.py:109`) and `test_session_manifest_strips_credentials` (`test_session_manifest.py:6`) both assert on filesystem/return-value state, not printed text, so they're unaffected by this step.

- [ ] **Step 4: Commit**

```bash
cd app && git add src/text2query/benchmark/reporting.py
git commit -m "refactor: drop archive-bookkeeping prints and paths invalidated by archiving"
```

---

### Task 5: Suppress the single-seed banner and drop stale-path suffixes

**Files:**
- Modify: `app/src/text2query/benchmark/runner.py:17-30` (`run_llm_generation`), `app/src/text2query/benchmark/runner.py:76,129` (inside `_run_single_generation`), `app/src/text2query/benchmark/runner.py:138-149` (`execute_generated_queries`), `app/src/text2query/benchmark/runner.py:184` (inside `_execute_single`), `app/src/text2query/benchmark/pipeline.py:267` (inside `execute_queries_to_csv`)

- [ ] **Step 1: Confirm the "config changed" substring tests still have something to match**

Run: `cd app && grep -n "config changed" tests/test_benchmark_caching.py`
Expected: three matches (the three `assert "config changed" in ...` lines). These lines stay untouched by this task — they guard `_run_single_generation`'s cache-invalidation message, which this task does not modify.

- [ ] **Step 2: Suppress `--- Seed N ---` when there's only one seed**

In `app/src/text2query/benchmark/runner.py`, change `run_llm_generation`:
```python
def run_llm_generation(
    questions_dir: Path,
    output_dir: Path,
    db_url: str,
    model: str,
    seeds: list[int] | None = None,
    query_ids: list[str] | None = None,
) -> None:
    for seed in seeds or [1]:
        seed_dir = output_dir / f"seed_{seed}"
        print(f"\n  --- Seed {seed} ---")
        _run_single_generation(
            questions_dir, seed_dir, db_url, model, seed=seed, query_ids=query_ids,
        )
```
to:
```python
def run_llm_generation(
    questions_dir: Path,
    output_dir: Path,
    db_url: str,
    model: str,
    seeds: list[int] | None = None,
    query_ids: list[str] | None = None,
) -> None:
    seeds = seeds or [1]
    for seed in seeds:
        seed_dir = output_dir / f"seed_{seed}"
        if len(seeds) > 1:
            print(f"\n  --- Seed {seed} ---")
        _run_single_generation(
            questions_dir, seed_dir, db_url, model, seed=seed, query_ids=query_ids,
        )
```

Change `execute_generated_queries`:
```python
def execute_generated_queries(
    queries_dir: Path,
    answers_dir: Path,
    db_url: str,
    seeds: list[int] | None = None,
    query_ids: list[str] | None = None,
) -> None:
    for seed in seeds or [1]:
        seed_queries = queries_dir / f"seed_{seed}"
        seed_answers = answers_dir / f"seed_{seed}"
        print(f"\n  --- Seed {seed} ---")
        _execute_single(seed_queries, seed_answers, db_url, query_ids=query_ids)
```
to:
```python
def execute_generated_queries(
    queries_dir: Path,
    answers_dir: Path,
    db_url: str,
    seeds: list[int] | None = None,
    query_ids: list[str] | None = None,
) -> None:
    seeds = seeds or [1]
    for seed in seeds:
        seed_queries = queries_dir / f"seed_{seed}"
        seed_answers = answers_dir / f"seed_{seed}"
        if len(seeds) > 1:
            print(f"\n  --- Seed {seed} ---")
        _execute_single(seed_queries, seed_answers, db_url, query_ids=query_ids)
```

- [ ] **Step 3: Write the failing test for the suppression behavior**

Add to `app/tests/test_multi_seed.py` (it already has the fakes needed — see `test_run_llm_generation_multi_seed_creates_subdirs` at line 19 for the pattern):

```python
def test_run_llm_generation_single_seed_omits_seed_banner(tmp_path, capsys):
    questions_dir = tmp_path / "questions"
    questions_dir.mkdir()
    (questions_dir / "01.md").write_text('# Business Question:\n  "test?"\n')
    output_dir = tmp_path / "out"

    import text2query.benchmark.runner as runner_mod
    from unittest.mock import patch
    from text2query.llm.ollama import GenerationResult

    with patch.object(runner_mod, "create_engine_for_database", lambda url: None), \
         patch.object(runner_mod, "render_schema", lambda engine, flags, metadata=None: "schema"), \
         patch.object(runner_mod, "load_tpch_metadata", lambda: {}), \
         patch.object(runner_mod.ollama, "warmup", lambda model: True), \
         patch.object(
             runner_mod.ollama, "generate_sql_with_retry",
             lambda *a, **kw: GenerationResult(sql="SELECT 1", raw_response="SELECT 1", prompt="p", error=None, retried=False),
         ):
        run_llm_generation(questions_dir, output_dir, "postgresql://fake", "m1", seeds=[1])

    out = capsys.readouterr().out
    assert "--- Seed" not in out
```

`GenerationResult`'s fields (`sql`, `raw_response`, `prompt`, `error`, `retried`) are confirmed against `app/src/text2query/llm/ollama.py:63-70`.

- [ ] **Step 4: Run test, verify pass; run multi-seed regression**

Run: `cd app && .venv/bin/pytest tests/test_multi_seed.py -v`
Expected: the new test passes; `test_run_llm_generation_multi_seed_creates_subdirs` (which uses `seeds=[1,2,3]`, i.e. more than one seed) still passes, confirming the banner still shows for multi-seed runs.

- [ ] **Step 5: Drop the stale-path suffixes**

In `app/src/text2query/benchmark/runner.py`, inside `_run_single_generation`, change:
```python
        print(f"  ✓ All {total} queries already generated in {output_dir}")
```
to:
```python
        print(f"  ✓ All {total} queries already generated")
```
and change:
```python
    print(f"  ✓ Generated {success} queries -> {output_dir}")
```
to:
```python
    print(f"  ✓ Generated {success} queries")
```

Inside `_execute_single`, change:
```python
        print(f"  ✓ All {total} answer files already exist in {answers_dir}")
```
to:
```python
        print(f"  ✓ All {total} answer files already exist")
```

In `app/src/text2query/benchmark/pipeline.py`, inside `execute_queries_to_csv`, change:
```python
    print(f"  ✓ Executed {success} queries -> {output_dir}")
```
to:
```python
    print(f"  ✓ Executed {success} queries")
```

Leave the two `⚠ ... clearing stale cache/answers in {dir}` lines untouched — those name a directory being acted on right now, not a path to check later, and `test_benchmark_caching.py` asserts on their `"config changed"` prefix.

- [ ] **Step 6: Run the full test suite**

Run: `cd app && .venv/bin/pytest tests/ -v`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
cd app && git add src/text2query/benchmark/runner.py src/text2query/benchmark/pipeline.py tests/test_multi_seed.py
git commit -m "fix: hide single-seed banner and stop printing paths archiving invalidates"
```

---

### Task 6: Wire the header and footer into `main()`, collapse stage titles

**Files:**
- Modify: `app/src/text2query/benchmark/benchmarking.py` (full rewrite of `main()` and `_run_single_model_benchmark`; add `_banner()`)
- Test: `app/tests/test_benchmarking.py`

**Interfaces:**
- Consumes: `format_session_header`, `format_run_summary` (Tasks 2, 3).
- Produces: `_banner(title: str) -> str` — local to `benchmarking.py`, a 60-column `─`-padded divider matching the header/footer's `═` width.

- [ ] **Step 1: Write the failing test for `_banner`**

Add to `app/tests/test_benchmarking.py`:

```python
from text2query.benchmark.benchmarking import _banner


def test_banner_pads_to_60_columns():
    line = _banner("Setup")
    assert len(line) == 60
    assert line.startswith("─── Setup ")


def test_banner_handles_long_titles_without_going_negative():
    line = _banner("Cross-Model Comparison")
    assert line.startswith("─── Cross-Model Comparison ")
    assert len(line) >= len("─── Cross-Model Comparison ") + 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && .venv/bin/pytest tests/test_benchmarking.py -k banner -v`
Expected: FAIL with `ImportError: cannot import name '_banner'`

- [ ] **Step 3: Add `_banner`**

In `app/src/text2query/benchmark/benchmarking.py`, add after the imports (before `@dataclass class BenchmarkPaths`):

```python
def _banner(title: str) -> str:
    """Render a light section divider padded to 60 columns, matching the header/footer width."""
    prefix = f"─── {title} "
    return prefix + "─" * max(3, 60 - len(prefix))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && .venv/bin/pytest tests/test_benchmarking.py -k banner -v`
Expected: PASS.

- [ ] **Step 5: Rewrite `_run_single_model_benchmark`**

Replace the whole function body (currently `benchmarking.py:43-85`):
```python
def _run_single_model_benchmark(
    model: str,
    paths: BenchmarkPaths,
    db_url: str,
    seeds: list[int] | None,
    query_ids: list[str] | None = None,
) -> list[dict]:
    """Run the full benchmark (generate + execute + report) for one model."""
    slug = model.replace(":", "_").replace("/", "_")
    output_dir = paths.output_dir / slug
    generated_answers_dir = paths.generated_answers_dir / slug
    report_dir = paths.report_dir / slug

    print(f"\n--- LLM SQL Generation (model: {model}, seeds: {len(seeds)}) ---\n")

    print("Generate SQL Queries via LLM")
    run_llm_generation(
        questions_dir=paths.questions_dir, output_dir=output_dir,
        db_url=db_url, model=model,
        seeds=seeds, query_ids=query_ids,
    )
    print()

    print("Execute LLM-Generated Queries")
    execute_generated_queries(
        queries_dir=output_dir, answers_dir=generated_answers_dir, db_url=db_url,
        seeds=seeds, query_ids=query_ids,
    )
    print()

    print("Generate Reports")
    results = generate_reports(
        generated_queries_dir=output_dir, reference_queries_dir=paths.queries_dir,
        generated_answers_dir=generated_answers_dir, reference_answers_dir=paths.answers_dir,
        report_dir=report_dir,
        seeds=seeds,
        model=model,
        selected_ids=query_ids,
        questions_dir=paths.questions_dir,
    )
    print()

    return results
```
with:
```python
def _run_single_model_benchmark(
    model: str,
    paths: BenchmarkPaths,
    db_url: str,
    seeds: list[int] | None,
    query_ids: list[str] | None = None,
) -> list[dict]:
    """Run the full benchmark (generate + execute + report) for one model."""
    slug = model.replace(":", "_").replace("/", "_")
    output_dir = paths.output_dir / slug
    generated_answers_dir = paths.generated_answers_dir / slug
    report_dir = paths.report_dir / slug

    print(_banner("SQL Generation"))
    run_llm_generation(
        questions_dir=paths.questions_dir, output_dir=output_dir,
        db_url=db_url, model=model,
        seeds=seeds, query_ids=query_ids,
    )
    print()

    print(_banner("Execution"))
    execute_generated_queries(
        queries_dir=output_dir, answers_dir=generated_answers_dir, db_url=db_url,
        seeds=seeds, query_ids=query_ids,
    )
    print()

    print(_banner("Evaluation"))
    results = generate_reports(
        generated_queries_dir=output_dir, reference_queries_dir=paths.queries_dir,
        generated_answers_dir=generated_answers_dir, reference_answers_dir=paths.answers_dir,
        report_dir=report_dir,
        seeds=seeds,
        model=model,
        selected_ids=query_ids,
        questions_dir=paths.questions_dir,
    )
    print()

    return results
```

(This is model name removed from the banner — it's already stated once, in the session header, and again in the per-model `═` divider for multi-model runs added in Step 7.)

- [ ] **Step 6: Run the existing structural test to confirm no regression**

Run: `cd app && .venv/bin/pytest tests/test_benchmarking.py::test_run_single_model_benchmark_builds_per_model_subdirs -v`
Expected: PASS — that test asserts on directory paths captured via mocks, not on printed text, so it's unaffected.

- [ ] **Step 7: Rewrite `main()`**

Add `import time` to the top of `app/src/text2query/benchmark/benchmarking.py` (alongside the existing `import logging`).

Add `format_session_header` to the existing `reporting` import block:
```python
from text2query.benchmark.reporting import (
    generate_reports,
    generate_cross_model_report,
    archive_session,
    write_session_manifest,
    format_run_summary,
    format_session_header,
)
```

Replace the entire `main()` function body from the `try:` line onward. Current (`benchmarking.py:136-263`):
```python
    try:
        # === Phase 1: Setup (shared across all models) ===
        print("\n--- Setup & Validation ---\n")

        # Resolve and validate query ID filter against available queries
        available = sorted(f.stem for f in paths.queries_dir.glob("*.sql"))
        query_ids, skipped = _resolve_query_id_filter(BENCHMARK_QUERY_IDS, available)
        if skipped:
            print(f"  ⚠ Unknown query IDs (skipped): {', '.join(skipped)}")
        if query_ids is not None and not query_ids:
            print("  ✗ No valid query IDs remain after filtering — aborting")
            sys.exit(1)
        if query_ids:
            print(f"  Query filter active: {len(query_ids)} / {len(available)} queries selected ({', '.join(query_ids)})")
            print()

        print("Data Generation")
        if BENCHMARK_DATA_PATH:
            print(f"  Using existing data: {BENCHMARK_DATA_PATH}")
            data_dir = Path(BENCHMARK_DATA_PATH)
        else:
            print(f"  Checking/Generating TPC-H data (scale factor: {BENCHMARK_SCALE_FACTOR})...")
            data_dir = generate_data(BENCHMARK_SCALE_FACTOR, data_dir)
        print()

        print("Validate Questions & Queries")
        validate_directories(paths.questions_dir, paths.queries_dir)
        print()

        print("Check Database Readiness")
        is_ready = check_database_readiness(db_url=DATABASE_URL)
        print()

        if not is_ready:
            print("Setup Database")
            setup_database(
                schema_file=paths.schema_file,
                data_dir=data_dir,
                db_url=DATABASE_URL,
            )
            print()
        else:
            print("Database already ready, skipping setup")
            print()

        print("Generate Answer Files")
        generate_answers(queries_dir=paths.queries_dir, answers_dir=paths.answers_dir, db_url=DATABASE_URL)
        print()

        # === Phase 2+3: Per-model benchmark ===
        if multi_model:
            print(f"\n{'=' * 60}")
            print(f"  Multi-Model Benchmark: {len(models)} models")
            print(f"{'=' * 60}\n")

        precomputed = {}
        for i, model in enumerate(models, 1):
            if multi_model:
                print(f"\n{'=' * 60}")
                print(f"  Model {i}/{len(models)}: {model}")
                print(f"{'=' * 60}")

            results = _run_single_model_benchmark(
                model=model,
                paths=paths,
                db_url=DATABASE_URL,
                seeds=seeds,
                query_ids=query_ids,
            )
            precomputed[model] = results

        # === Cross-model comparison (if multi-model) ===
        if multi_model:
            print("\n--- Cross-Model Comparison ---\n")
            generate_cross_model_report(
                models=models,
                reference_queries_dir=paths.queries_dir,
                report_dir=paths.report_dir,
                precomputed=precomputed,
                seeds=seeds,
                selected_ids=query_ids,
            )
            print()

        # === Archive ===
        print("\n--- Archiving ---\n")

        fingerprints = collect_fingerprints(paths.output_dir)

        print("Archive Session")
        session_dir = archive_session(
            queries_dir=paths.output_dir, answers_dir=paths.generated_answers_dir,
            report_dir=paths.report_dir, results_base=paths.results_base,
        )

        write_session_manifest(
            session_dir,
            models=models,
            seeds=seeds,
            query_ids=query_ids,
            scale_factor=BENCHMARK_SCALE_FACTOR,
            generation_parameters={
                "temperature": LLM_TEMPERATURE,
                "max_tokens": LLM_MAX_TOKENS,
                "num_ctx": LLM_NUM_CTX,
            },
            prompt_flags=asdict(PROMPT_FLAGS),
            fingerprints=fingerprints,
            database_url=DATABASE_URL,
        )
        print()

        print(format_run_summary(
            total_questions=len(list(paths.questions_dir.glob("*.md"))),
            total_ground_truth=len(list(paths.queries_dir.glob("*.sql"))),
            query_ids=query_ids,
            models=models,
            num_seeds=BENCHMARK_NUM_SEEDS,
            session_dir=session_dir,
            database_url=DATABASE_URL,
            prompt_flags=asdict(PROMPT_FLAGS),
        ))

        return 0

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
```

New:
```python
    start_time = time.monotonic()

    try:
        # Resolve the query filter, then announce the whole session up front.
        available = sorted(f.stem for f in paths.queries_dir.glob("*.sql"))
        query_ids, skipped = _resolve_query_id_filter(BENCHMARK_QUERY_IDS, available)

        print(format_session_header(
            scale_factor=BENCHMARK_SCALE_FACTOR,
            models=models,
            total_available=len(available),
            query_ids=query_ids,
            num_seeds=BENCHMARK_NUM_SEEDS,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            num_ctx=LLM_NUM_CTX,
            prompt_flags=asdict(PROMPT_FLAGS),
            database_url=DATABASE_URL,
        ))

        if skipped:
            print(f"  ⚠ Unknown query IDs (skipped): {', '.join(skipped)}")
        if query_ids is not None and not query_ids:
            print("  ✗ No valid query IDs remain after filtering — aborting")
            sys.exit(1)

        # === Phase 1: Setup (shared across all models) ===
        print(_banner("Setup"))
        if BENCHMARK_DATA_PATH:
            print(f"  Using existing data: {BENCHMARK_DATA_PATH}")
            data_dir = Path(BENCHMARK_DATA_PATH)
        else:
            data_dir = generate_data(BENCHMARK_SCALE_FACTOR, data_dir)

        validate_directories(paths.questions_dir, paths.queries_dir)

        is_ready = check_database_readiness(db_url=DATABASE_URL)
        if not is_ready:
            setup_database(
                schema_file=paths.schema_file,
                data_dir=data_dir,
                db_url=DATABASE_URL,
            )

        generate_answers(queries_dir=paths.queries_dir, answers_dir=paths.answers_dir, db_url=DATABASE_URL)
        print()

        # === Phase 2+3: Per-model benchmark ===
        if multi_model:
            print("═" * 60)
            print(f"  Multi-Model Benchmark: {len(models)} models")
            print("═" * 60)
            print()

        precomputed = {}
        for i, model in enumerate(models, 1):
            if multi_model:
                print("═" * 60)
                print(f"  Model {i}/{len(models)}: {model}")
                print("═" * 60)
                print()

            results = _run_single_model_benchmark(
                model=model,
                paths=paths,
                db_url=DATABASE_URL,
                seeds=seeds,
                query_ids=query_ids,
            )
            precomputed[model] = results

        # === Cross-model comparison (if multi-model) ===
        if multi_model:
            print(_banner("Cross-Model Comparison"))
            generate_cross_model_report(
                models=models,
                reference_queries_dir=paths.queries_dir,
                report_dir=paths.report_dir,
                precomputed=precomputed,
                seeds=seeds,
                selected_ids=query_ids,
            )
            print()

        # === Archive ===
        print(_banner("Archiving"))

        fingerprints = collect_fingerprints(paths.output_dir)

        session_dir = archive_session(
            queries_dir=paths.output_dir, answers_dir=paths.generated_answers_dir,
            report_dir=paths.report_dir, results_base=paths.results_base,
        )

        write_session_manifest(
            session_dir,
            models=models,
            seeds=seeds,
            query_ids=query_ids,
            scale_factor=BENCHMARK_SCALE_FACTOR,
            generation_parameters={
                "temperature": LLM_TEMPERATURE,
                "max_tokens": LLM_MAX_TOKENS,
                "num_ctx": LLM_NUM_CTX,
            },
            prompt_flags=asdict(PROMPT_FLAGS),
            fingerprints=fingerprints,
            database_url=DATABASE_URL,
        )
        print("  ✓ Archived")
        print()

        elapsed = time.monotonic() - start_time
        print(format_run_summary(precomputed, models, session_dir, elapsed))

        return 0

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
```

Note what disappeared and why, in case a reviewer asks:
- The `"Query filter active: N / M queries selected"` line is gone — the header's `Queries` field already states this.
- The five per-stage title prints (`"Data Generation"`, `"Validate Questions & Queries"`, `"Check Database Readiness"`, `"Setup Database"` / `"Database already ready, skipping setup"`, `"Generate Answer Files"`) are gone — each wrapped function already narrates itself (e.g. `check_database_readiness` already prints `"✓ Database is ready"` / `"✗ Database needs setup"`), so the wrapper title was pure echo.
- `"Archive Session"` title is gone in favor of a single `"  ✓ Archived"` confirmation after the (now silent) archive+manifest calls.

- [ ] **Step 8: Run the full test suite**

Run: `cd app && .venv/bin/pytest tests/ -v`
Expected: All PASS.

- [ ] **Step 9: Manual smoke check (no automated test exists for `main()` itself — see note below)**

`main()` is CLI orchestration with zero direct test coverage before this plan (confirmed: `grep -rn "benchmarking.main" tests/` returns nothing) — the codebase's existing convention is to test the functions `main()` calls, not `main()` itself, since it reads live config from `os.environ` and drives real I/O. This plan follows that convention rather than bolting on an artificial integration test.

Instead, do one manual pass before merging:

```bash
cd /home/onehalfa/Projects/text2query-code
docker compose --profile benchmark up --build --no-log-prefix --attach benchmark benchmark
```

Confirm by eye:
1. A `═`-bordered header prints first, before any other output, showing model, queries, seeds, evaluations, metrics, prompt features, LLM params, and a redacted database URL.
2. No stage title is immediately followed by a line that just restates it.
3. With `BENCHMARK_NUM_SEEDS=1` (the repo default), no `--- Seed 1 ---` line appears anywhere.
4. The closing block shows `Result F1`, `AST similarity`, `Exact matches`, `Failures`, and `Session`, not the model/prompt-flags/database-URL block from before.
5. No line anywhere contains the Postgres password (`grep -c password` against a captured log should be `0`).

- [ ] **Step 10: Commit**

```bash
cd app && git add src/text2query/benchmark/benchmarking.py tests/test_benchmarking.py
git commit -m "feat: wire session header and score-based summary into benchmark main(), collapse duplicate stage titles"
```

---

## Self-Review Notes

- **Spec coverage:** Header (Task 2) ✓, footer rewrite (Task 3) ✓, all 9 audit findings — #1/#2/#3 (Task 6, duplicate titles + banners), #4 (Task 5, seed banner), #5 (Tasks 4 & 5, stale paths), #6 (Task 4, archive bookkeeping), #7 (Tasks 4 & 6, session dir stated once), #8 (Task 6, single blank line), #9 (Task 6, header redacts, footer never prints the URL) ✓. `METRICS` single-source-of-truth (Task 1) ✓. 60-column banner consistency (Tasks 2 & 6, shared width, `═` vs `─` split by "session-level" vs "stage-level") ✓.
- **Placeholders:** none — every step has literal code, not descriptions of code.
- **Type consistency:** `format_run_summary`'s new signature (`precomputed, models, session_dir, elapsed`) is defined once in Task 3 and consumed exactly that way in Task 6, Step 7. `format_session_header`'s keyword args are defined in Task 2 and consumed with the same names in Task 6, Step 7. `_field`, `_plural`, `_aggregate_model_results`, `_format_elapsed`, `_banner` each have exactly one producer task and are consumed with matching names elsewhere.
- **Scope:** touches exactly the 5 files named in the spec's "Scope" section (`benchmarking.py`, `reporting.py`, `runner.py`, `pipeline.py`, `test_reporting.py`), plus `test_multi_seed.py` and `test_benchmarking.py` for the new behavioral tests the spec's testing section implied but didn't enumerate file-by-file. No scoring, archiving, or file-artifact logic changes.
