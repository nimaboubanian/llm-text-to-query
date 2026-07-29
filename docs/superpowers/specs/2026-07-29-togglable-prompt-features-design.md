# Togglable Prompt-Engineering Features — Design

Date: 2026-07-29
Status: approved (brainstormed with user)

## Goal

Make every prompt-engineering improvement technique — new ones from the thesis
research (`tmp/promptEng.md`, `tmp/How.md`) and any technique already baked into
the project — an independently togglable feature, controlled from the compose
file, so benchmark runs can measure the effect of each feature and each
combination. Features are implemented one at a time; after each one the user
runs tests and a benchmark and confirms before the next begins.

## Decisions (made during brainstorming)

1. **Granularity:** one toggle per technique — 9 flags.
2. **Prompt architecture:** code-side section composer (flat builder function).
   The user-editable template file is removed.
3. **Benchmark sweeps:** one feature combination per benchmark run; runs are
   compared afterwards via recorded flag manifests. No in-run sweeping.
4. **Enrichment metadata:** curated, checked-in TPC-H metadata file; no live DB
   sampling.
5. **Retry:** execution-guided retry lives in the shared generation layer, used
   identically by app mode and benchmark mode.
6. **Composer style:** flat `build_prompt()` function with if-branches
   (approach A) — no section registry, no template engine.

## 1. Feature flags & config

Nine env vars in the compose `x-config` block. **All default off; the all-off
state is the experimental baseline.**

| Env var | Type | Feature |
| --- | --- | --- |
| `PROMPT_SCHEMA_DDL` | bool | Schema as `CREATE TABLE` DDL instead of prose |
| `PROMPT_SCHEMA_FK` | bool | Explicit FK annotations (`REFERENCES t(c)` in DDL mode; keeps/drops existing `FK(...) ->` notation in prose mode) |
| `PROMPT_SCHEMA_DESCRIPTIONS` | bool | NL column descriptions from curated metadata, as `--` comments |
| `PROMPT_SCHEMA_SAMPLES` | bool | Inline sample values for categorical columns, as `--` comments |
| `PROMPT_XML_STRUCTURE` | bool | XML-tagged sections (`<schema>`, `<examples>`, `<rules>`, `<query>`) |
| `PROMPT_FEW_SHOT` | int (0–3) | Number of static schema-agnostic Question/SQL examples; 0 = off; values above 3 clamp to 3 |
| `PROMPT_PLANNING` | bool | Lightweight planning scaffold (list tables + join path as SQL comments before the query) |
| `PROMPT_STRICT_OUTPUT` | bool | Emphatic "Return ONLY the SQL query, no explanation, no markdown" rules block |
| `RETRY_ON_ERROR` | bool | Single execution-guided retry with the raw Postgres error appended |

`core/config.py` gains a frozen dataclass `PromptFlags` holding all nine,
populated once at import via the existing `_env` helper. It is passed
explicitly into the builder and retry code — no global reads inside the
builder, so tests construct arbitrary combinations directly.

**Baseline change (deliberate, noted for comparability):** the current template
file contains the strict output rules unconditionally. To make
`PROMPT_STRICT_OUTPUT` a real toggle, the new all-off baseline keeps only a
minimal instruction ("Generate a PostgreSQL query to answer: ..."), and the
emphatic rules move behind the flag. Results from the new baseline are
therefore not directly comparable with pre-refactor result dirs
(`benchmark/results/2026-07-13_*`, `2026-07-24_*`).

## 2. Prompt builder (`llm/prompt_builder.py`)

Single function:

```python
def build_prompt(flags: PromptFlags, schema_str: str, question: str) -> str
```

Sections assembled as a list of strings and joined, in fixed salience order
(the order itself is not a toggle — the research treats it as strictly better,
and today's template already follows it approximately):

1. **Role** — fixed line ("You are a PostgreSQL expert...").
2. **Schema** — `schema_str` (already enriched per schema flags; see §3).
3. **Examples** — if `few_shot > 0`, the first N of 3 static Question/SQL
   pairs, hardcoded constants in the module. Spider-style, deliberately
   non-TPC-H schemas to avoid context pull.
4. **Planning** — if `planning`, instruction to list relevant tables and the
   join path as SQL comments before the final query (comments so the existing
   extractor still finds the SELECT).
5. **Question** — the user query.
6. **Rules** — minimal instruction always; emphatic rules block appended if
   `strict_output`. Always the last section (recency).

`xml_structure` wraps each section in its tag; the section order is identical
with or without it, so the XML flag isolates markup effect from ordering.

**Removed:** `prompts/sql_generation.txt`, `PROMPT_TEMPLATE_PATH`,
`llm/prompt_loader.py`, and the compose `prompts/` volume mounts. The builder
is the single source of prompt truth. A fully-custom prompt override is out of
scope (add as a future flag if ever needed, not as a parallel mechanism).

**Known limitation:** with `planning` on, the model emits non-SQL text before
the query; SQL extraction (`_clean_sql_response`) is unchanged, so extraction
failures under this flag are part of what the ablation measures.

## 3. Schema rendering & curated metadata

`database/schema.py`:

- `get_database_schema_string(engine)` — unchanged prose format (baseline).
- `render_schema(engine, flags, metadata) -> str` — new; dispatches prose vs
  DDL per `schema_ddl`, then applies the three enrichments.

DDL mode builds `CREATE TABLE` blocks from the same SQLAlchemy inspector data
(names, types, primary keys). `schema_fk` adds inline `REFERENCES table(col)`
in DDL mode; in prose mode it controls the existing `FK(...) ->` notation —
so FK-off removes today's hints, making current behavior an ablatable
enriched state. Descriptions and samples append `-- comment` text per column
(parenthetical text in prose mode).

**Metadata file:** `db/tpch_metadata.json`, checked in, written once from the
TPC-H spec:

```json
{
  "lineitem": {
    "l_extendedprice": {"desc": "extended price (quantity * part price)"},
    "l_linestatus": {"desc": "line status flag",
                      "samples": ["'O' (open)", "'F' (fulfilled)"]}
  }
}
```

Columns absent from the file get no enrichment — app mode against a
non-TPC-H database degrades gracefully with no separate code path. The file
is loaded once per process alongside the cached schema.

Because the rendered schema feeds `GenerationFingerprint.schema`, all four
schema flags invalidate generation caches automatically.

## 4. Execution-guided retry (shared code path)

In `llm/ollama.py`:

```python
def generate_sql_with_retry(question, schema_str, model, seed,
                            validate: Callable[[str], str | None]) -> GenerationResult
```

`validate(sql)` returns an error message or `None`. The llm layer never
imports the database layer; server and benchmark each pass a validator built
on the existing executor. Flow: generate → if extraction failed **or**
validator returns an error → one re-prompt (original prompt + the model's SQL
+ the raw error + "fix the query, return only the corrected SQL"), same seed
and model → return the second result unconditionally.

`GenerationResult` gains `retried: bool` and `retry_reason: str | None`;
reports count recoveries.

**Validator = `EXPLAIN <sql>`**, not full execution. EXPLAIN surfaces the
error class retry provably recovers (syntax, unknown column/table, type
mismatch) in milliseconds; full execution of TPC-H queries at sf1 would
roughly double generation-stage time for no extra recovery on that class.
Ceiling: pure runtime errors (e.g. division by zero) are not caught.

Two retry triggers:

- validator error → error text fed back (the research case);
- extraction failure → retried with a "return only SQL" reason.

Benchmark mode: retry happens inside the generation stage; queries are still
written to files and the separate execution-to-CSV stage is untouched.
Per-query timing naturally includes the retry attempt.

## 5. Fingerprinting, results & compose wiring

- `GenerationFingerprint.prompt_template` now holds the **built prompt
  skeleton**: `build_prompt(flags, schema="{schema}", question="{query}")`
  with sentinel placeholders. Any flag that changes prompt structure changes
  the skeleton — cache invalidation stays automatic, no version constant.
- `RETRY_ON_ERROR` does not change the skeleton, so it becomes an explicit
  fingerprint field.
- The full 9-flag dict is recorded in `session_manifest.json` and echoed in
  the report header. Result dir naming stays timestamp-based; runs are
  compared by diffing manifests.
- The nine vars are added to the compose `x-config` block with one-line
  comments; `app` and `benchmark` services inherit them as-is.

## 6. Rollout order & testing

One confirmed step at a time. After each step: unit tests pass, the user runs
a benchmark with the new flag on, confirms, then the next step begins.

- **Step 0 — scaffolding refactor:** `PromptFlags`, `prompt_builder.py`,
  remove `prompt_loader.py` + template file + mounts, fingerprint and
  manifest changes. All flags off; user runs the new baseline benchmark to
  anchor comparisons.
- **Steps 1–9 — one flag each,** in order of expected impact and
  independence:
  1. `PROMPT_STRICT_OUTPUT`
  2. `PROMPT_SCHEMA_DDL`
  3. `PROMPT_SCHEMA_FK`
  4. `PROMPT_SCHEMA_DESCRIPTIONS` (includes `db/tpch_metadata.json`)
  5. `PROMPT_SCHEMA_SAMPLES`
  6. `PROMPT_XML_STRUCTURE`
  7. `PROMPT_FEW_SHOT`
  8. `PROMPT_PLANNING`
  9. `RETRY_ON_ERROR`

**Testing:** builder unit tests assert flag → expected prompt fragment (and
absence when off); one test pins the all-off baseline prompt verbatim;
metadata-file test validates every key is a real TPC-H table/column; retry
tested with a stub validator, no DB. No integration-test framework — the
per-step benchmark run is the integration test.

## Out of scope

- In-run feature sweeps (`BENCHMARK_FEATURE_SETS`) — add later if manual
  combo runs get tedious.
- Dynamic few-shot retrieval (MQS/DAIL), multi-stage pipelines (DIN-SQL,
  DTS-SQL) — research applies them to 13B+ models; revisit if the model
  roster grows.
- Changes to SQL extraction, similarity scoring, or report formats beyond the
  flag manifest and retry counts.

## Known limitations

- `RETRY_ON_ERROR`'s retry prompt (`llm/ollama.py`) ends with wording that closely
  resembles `PROMPT_STRICT_OUTPUT`'s emphatic rules text. A `RETRY_ON_ERROR=true`
  run is therefore not a clean ablation of retry in isolation — retried queries
  get strict-output-like phrasing regardless of the `PROMPT_STRICT_OUTPUT` flag's
  own setting. Account for this when interpreting retry-ablation results.
