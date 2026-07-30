# Similarity Metric Improvements — Design

Date: 2026-07-30
Status: Approved (approach A)
Source material: `tmp/similarity_what.md`, `tmp/similarity_how.md` (backed by `tmp/Thesis/`)

## Context

`app/src/text2query/benchmark/similarity.py` already implements most of the
"Optimal Metric Framework" from the source docs: Result F1 with ordered mode
for ORDER BY+LIMIT, column permutation alignment (≤8 columns), the
both-empty → F1 = 1.0 safeguard, a 5-category error taxonomy, raw-AST
similarity via sqlglot diff, and independent (non-composite) metrics.

Three gaps remain, decided as follows:

| Decision | Outcome |
| --- | --- |
| Float comparison | True epsilon matching, configurable via compose (replaces rigid `round(4)`) |
| AST normalization debate (Option A vs B) | Report **both**: raw `ast_similarity` and new always-on `ast_similarity_normalized` |
| Test-suite execution, LLM-judge/FLEX | Out of scope (stay single-DB, no LLM calls); thesis cites known FP/FN rates of single-DB EX as a limitation |

Explicitly skipped, with rationale: string metrics (BLEU/Jaccard — redundant
with AST comparison per the docs), composite weighted scores (rejected by the
docs), ordered-mode for ORDER BY-without-LIMIT (current both-required
behavior matches the docs; positional comparison under ties would create
false negatives), partial credit on column-count mismatch (YAGNI),
configurable permutation cap (constant is fine).

**The only new compose toggle is `BENCHMARK_FLOAT_EPSILON`.** Normalized AST
similarity is always-on (a mode toggle would fragment comparability across
runs).

## 1. Epsilon-based float matching

In `_result_set_comparison`, replace the current round-to-4-decimals-then-
hash-exactly mechanism with tolerance-aware matching. Two float values are
equal when `|a − b| ≤ ε` (absolute tolerance); two NaN/NULL values also
match. Non-float columns keep exact comparison.

- **Ordered mode** (reference has top-level ORDER BY and LIMIT): row *i*
  compares to row *i*; per-column `isclose` on float columns, exact
  elsewhere.
- **Bag mode**: group both result sets by their non-float column values
  (exact key). Within each group, sort both sides' float vectors and
  zip-compare positionally; a pair matches when every float column is
  within ε. Matched pairs feed precision/recall exactly as today.
- Sort-then-zip pairing is not provably optimal bipartite matching when
  multiple float columns interact; mark with a `ponytail:` comment naming
  optimal assignment as the upgrade path. On real TPC-H results it is
  equivalent.
- Untouched: both-empty safeguard, column-count gate (flat 0.0),
  `_align_columns` permutation search (it only picks a column ordering; the
  epsilon matcher does the scoring).

## 2. Normalized AST similarity (`ast_similarity_normalized`)

New always-on metric next to raw `ast_similarity`. Same
`kept / (kept + edits)` formula over `sqlglot.diff`, but both trees first
pass through `sqlglot.optimizer.optimize(tree, schema=…, dialect="postgres")`,
which performs the docs' normalization pipeline (column qualification /
alias removal, predicate normalization, canonicalization, subquery
unnesting) with machinery already installed (sqlglot ≥ 26).

- **Schema**: parsed lazily once from `benchmark/.tpch/schema.sql` (the DDL
  the benchmark already loads) into a `{table: {column: type}}` dict, cached
  at module level.
- **Fallback (approved)**: normalization is best-effort per side — if
  `optimize()` raises for one query, that side falls back to its raw tree.
  The column is `None` only when a query fails to parse at all (the same
  condition that nulls raw `ast_similarity`). Canonicalizer failure must not
  zero out a model's score.
- **Diagnostic value**: the gap between raw and normalized similarity
  separates style divergence (large gap) from real structural error (small
  gap).

## 3. Config & compose wiring

- `core/config.py`:
  `BENCHMARK_FLOAT_EPSILON = _env("BENCHMARK_FLOAT_EPSILON", 1e-4, float)` —
  follows the existing `_env` pattern.
- `compose.yml.example`: one documented line, e.g.
  `BENCHMARK_FLOAT_EPSILON: "1e-4"  # Absolute float tolerance; loosen to 1e-2 for money-heavy queries`.
- `similarity.py` reads the config default; `evaluate_query` gains no new
  required parameters.

## 4. Reporting

`ast_similarity_normalized` joins `CSV_COLUMNS`, `METRICS`, and
`METRIC_LABELS` in `reporting.py`; every table/summary surface that shows
AST similarity gains the normalized sibling column. Purely mechanical.

## 5. Testing

Extend `app/tests/test_similarity.py`:

- **Epsilon**: one parametrized case covering within-ε match (including a
  rounding-boundary pair that `round(4)` used to fail) and beyond-ε
  mismatch; NaN-vs-NaN equality; ordered-mode comparison with epsilon.
- **Normalization**: alias divergence (`SELECT l.x FROM t l` vs
  `SELECT t.x FROM t`) → raw < 1.0, normalized = 1.0; commutative predicate
  swap → normalized = 1.0; optimizer-failure fallback behaves like raw
  trees; unparseable SQL → both AST columns `None`.
- **Reporting**: existing reporting tests updated for the new column.

## Non-goals

- No file splits; `similarity.py` stays single-file (~250 lines after).
- No new dependencies.
- No toggles beyond `BENCHMARK_FLOAT_EPSILON`.
- No changes to error classification, `_align_columns`, or ordered-mode
  policy.
