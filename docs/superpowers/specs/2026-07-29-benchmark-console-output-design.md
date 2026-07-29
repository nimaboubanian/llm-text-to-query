# Benchmark Console Output — Session Header and Redundancy Cleanup

**Date:** 2026-07-29
**Status:** Approved, pending implementation

## Problem

`docker compose --profile benchmark up` produces console output with two defects:

1. **No session header.** A run gives no upfront statement of what is being
   measured: which prompt features are active, which metrics are scored, which
   dataset and scale factor, when the run started.

2. **Pervasive redundancy.** Nine distinct classes of repeated or misleading
   output, catalogued below.

The two are coupled. `format_run_summary` — the closing "Benchmark Complete"
block — reports *no results at all*; it restates model, seeds, query IDs,
prompt features, and database URL. Adding a header naively would print that
configuration block twice per session.

The resolution is a single reorganization: **configuration belongs at the top
(intent), results belong at the bottom (outcome).** This adds the header,
removes the duplication, and fixes a summary that summarizes nothing.

## Redundancy Audit

| # | Finding | Location |
|---|---|---|
| 1 | Stage title echoes the first narration line inside it (4×) | `Data Generation`→`Generating TPC-H data...`; `Validate Questions & Queries`→`Validating directories...`; `Check Database Readiness`→`Checking database readiness...`; `Generate Answer Files`→`Checking answer files...` |
| 2 | `Generate SQL Queries via LLM` restates the banner above it | `benchmarking.py:56,58` |
| 3 | Model name printed 4× | section banner, `Warming up X`, multi-model banner, closing summary |
| 4 | `--- Seed N ---` printed twice per model (generation + execution); noise at `NUM_SEEDS=1` | `runner.py:27,148` |
| 5 | Intermediate paths printed, then invalidated — those directories are *moved* into the session dir at archive time, so the printed paths do not exist when the run ends | `queries/<model>/seed_N`, `answers/...`, `reports/<model>` |
| 6 | Archive bookkeeping exposes internal mechanics | `reporting.py:338,357` |
| 7 | Session directory printed 3× | `Session archived ->`, `Session manifest ->`, `Session:` |
| 8 | Double blank lines from `print()` plus `\n`-prefixed banners | `benchmarking.py` throughout |
| 9 | **Password leaked in cleartext** — the closing summary prints the raw `DATABASE_URL` while `write_session_manifest` redacts the same value via `_redact_db_url` | `reporting.py:443` vs `:393` |

## Design

### 1. Session header

New `format_session_header()` in `reporting.py`, printed once at the top of
`main()` before any stage runs.

```
════════════════════════════════════════════════════════════
  text2query Benchmark · TPC-H (scale factor 1)
  2026-07-29 14:32:05
════════════════════════════════════════════════════════════
  Model            qwen2.5-coder:7b
  Queries          3 of 22 (01, 07, 16)
  Seeds            1
  Evaluations      3  (3 queries × 1 seed × 1 model)
  Metrics          Result F1, AST similarity
  Prompt features  schema_ddl, schema_fk, schema_descriptions,
                   schema_samples, xml_structure, few_shot=1,
                   planning, strict_output, retry_on_error
  LLM params       temp=0.1, max_tokens=2048, num_ctx=4096
  Database         postgresql://***:***@postgres:5432/testdb
════════════════════════════════════════════════════════════
```

Rendering rules:

- `Model` becomes `Models` with a comma-separated list when
  `len(models) > 1`.
- `Queries` renders `22 of 22 (all)` when no filter is active.
- `Prompt features` reuses the existing enabled-flag rendering from
  `format_run_summary` (booleans by name, non-booleans as `key=value`), wrapped
  to the header width; renders `none (baseline)` when no flag is set.
- `Database` is passed through `_redact_db_url`.

**Ordering change:** `_resolve_query_id_filter` moves above the header print in
`main()` so the header can state accurate query counts. It is a pure glob over
`queries_dir` with no side effects, so the move is safe. If the query
directory is missing, the header reports `0 of 0` and `validate_directories`
raises immediately afterward through the existing error path.

### 2. Metrics constant

New module-level pair in `reporting.py`:

```python
METRICS = ("result_f1", "ast_similarity")
METRIC_LABELS = {"result_f1": "Result F1", "ast_similarity": "AST similarity"}
```

This replaces the `metrics_to_aggregate` list currently duplicated at
`reporting.py:140` and `reporting.py:249`, and drives the header's `Metrics`
line — so the header cannot drift from what is actually scored.

Result precision and recall remain computed and exported to `results.csv`;
they are not headline metrics and do not appear in the header.

### 3. Closing summary

`format_run_summary()` is rewritten to report outcomes. Signature shrinks to
`(precomputed, models, session_dir, elapsed)`. Means are computed from the
already-evaluated `precomputed` dict via the existing `_compute_stats`; no
re-evaluation occurs.

Single model:

```
════════════════════════════════════════════════════════════
  Benchmark Complete  ·  elapsed 4m 12s
════════════════════════════════════════════════════════════
  Result F1        0.7412   (mean over 3 queries × 1 seed)
  AST similarity   0.8130
  Exact matches    2 / 3
  Failures         0

  Session          benchmark/results/2026-07-29_14-32-05
════════════════════════════════════════════════════════════
```

Multiple models:

```
  Model                 Result F1   AST sim   Exact   Fail
  qwen2.5-coder:7b         0.7412    0.8130   2 / 3      0
  llama3.1:8b              0.6120    0.7740   1 / 3      1

  Session          benchmark/results/2026-07-29_14-32-05
```

Definitions:

- **Exact matches** keeps the existing rule — per-query mean `result_f1 == 1.0`
  (`reporting.py:206`). Flat results are grouped by `query_id` and averaged
  before comparison.
- **Failures** counts flat results whose `status` is not `"ok"`.
- **Elapsed** derives from a `time.monotonic()` mark taken at the top of
  `main()`, formatted as `Xm Ys`.

The database URL does not appear in the footer at all; it is stated once, in
the header, redacted.

### 4. Stage narration

All nine audit findings are addressed:

- Stage title and its echo collapse to one line each.
- Banners become `─── Setup ───`, `─── SQL Generation ───`,
  `─── Execution ───`, `─── Evaluation ───`, `─── Archiving ───`, emitted by a
  small `_banner()` helper local to `benchmarking.py`. Each banner is padded
  with `─` to 60 columns, matching the header and footer rules.
- `--- Seed N ---` prints only when `len(seeds) > 1`.
- Archive bookkeeping (`Moved N dirs...` ×3) is removed.
- Intermediate output paths are removed; the session directory is stated once,
  in the footer.
- Exactly one blank line separates stages.
- `_redact_db_url` applies to the header's `Database` line.

Setup phase on a warm cache, ~18 lines reduced to ~8. What actually disappeared
is the duplicated wrapper *titles* around each step — the underlying pipeline
functions (`validate_directories`, `check_database_readiness`,
`generate_answers` in `pipeline.py`) keep their own
progress-line-then-result-line pairs, since those lines carry real information
(which specific thing succeeded) that a single collapsed line would lose, and
matter more on a cold cache where the underlying work takes real time:

```
─── Setup ──────────────────────────────────────────────────
  ✓ Using cached data: benchmark/.tpch/data/sf1
  Validating directories...
  ✓ Questions: benchmark/.tpch/questions
  ✓ Queries: benchmark/.tpch/queries
  Checking database readiness...
  ✓ Database is ready
  Checking answer files...
  ✓ All 22 answer files exist
```

Lines expand naturally when work actually occurs — a cold cache still narrates
generation, schema load, row counts, and index building.

### 5. Per-query progress

Unchanged. `  [1/3] Q01... ✓` reports live progress on the slowest stage, where
a single query can take minutes. This is informative, not redundant.

## Placement

Header and footer live in `reporting.py`, beside the function they replace.
Stage banners stay local to `benchmarking.py`. No new module is introduced —
commit `c5b310f` removed a single-consumer module, and this work does not
justify adding one back.

## Scope

Files touched: `benchmarking.py`, `reporting.py`, `runner.py`, `pipeline.py`,
`test_reporting.py`.

**Terminal output only.** Scoring, archiving, and the written `.md`, `.csv`,
and `.json` artifacts are unchanged.

## Testing

- `format_session_header` renders enabled prompt flags, accurate query counts,
  and the metrics list.
- `format_session_header` redacts credentials: `"password" not in header`.
- `format_run_summary` renders aggregate scores for a single model.
- `format_run_summary` renders one row per model for multi-model runs.
- `format_run_summary` omits the database URL entirely.
- Existing tests at `test_reporting.py:78-101` assert on the old
  configuration-based summary and are rewritten against the new signature.
