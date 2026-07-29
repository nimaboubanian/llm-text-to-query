# Togglable Prompt-Engineering Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every prompt-engineering technique (9 total, from the thesis research) an independently togglable feature controlled by compose env vars, so benchmark runs can measure each feature and combination.

**Architecture:** A frozen `PromptFlags` dataclass (read once from env in `core/config.py`) feeds a flat `build_prompt()` composer in `llm/prompt_builder.py` and a `render_schema()` renderer in `database/schema.py`. The old file-based template (`prompts/sql_generation.txt` + `llm/prompt_loader.py`) is deleted. Flags flow into `GenerationFingerprint` (mostly automatically, via the built prompt skeleton and rendered schema) and into `session_manifest.json`.

**Tech Stack:** Python stdlib + existing deps only (SQLAlchemy inspector, sqlglot already present). No new dependencies. Tests: pytest (`cd app && uv run pytest tests/ -q`; plain `python -m pytest` works too).

**Spec:** `docs/superpowers/specs/2026-07-29-togglable-prompt-features-design.md`

## Global Constraints

- All 9 flags default **off**; the all-off state is the experimental baseline and must be pinned by a verbatim test.
- Env var names (exact): `PROMPT_SCHEMA_DDL`, `PROMPT_SCHEMA_FK`, `PROMPT_SCHEMA_DESCRIPTIONS`, `PROMPT_SCHEMA_SAMPLES`, `PROMPT_XML_STRUCTURE`, `PROMPT_FEW_SHOT` (int, clamps to 0–3), `PROMPT_PLANNING`, `PROMPT_STRICT_OUTPUT`, `RETRY_ON_ERROR`.
- Section order in the prompt is fixed (salience order): role, schema, examples, planning, question, rules. Never reordered by any flag.
- No global reads inside `build_prompt`/`render_schema` — flags always passed as a parameter (the `PROMPT_FLAGS` singleton is passed in by callers).
- Each task ends with a **USER GATE**: user runs a benchmark with the new flag on and confirms before the next task starts. Do not proceed past a gate without confirmation.
- Commits: conventional style, **no Co-Authored-By trailer** (user preference).
- Compose changes go to **both** `compose.yml` (local, gitignored) and `compose.yml.example` (tracked). `compose.amd.yml`/`compose.nvidia.yml` are GPU overlays with no config block — never touched.

---

### Task 0: Scaffolding — PromptFlags, prompt builder, remove file template

**Files:**
- Modify: `app/src/text2query/core/config.py`
- Create: `app/src/text2query/llm/prompt_builder.py`
- Create: `app/tests/test_prompt_builder.py`
- Modify: `app/src/text2query/llm/ollama.py` (drop prompt_loader, use builder)
- Modify: `app/src/text2query/server/main.py:14,104` (drop prompt_loader import/call)
- Modify: `app/src/text2query/benchmark/runner.py:8,54` (fingerprint uses skeleton)
- Modify: `app/src/text2query/benchmark/reporting.py:368` (`write_session_manifest` gains `prompt_flags`), `:402` (`format_run_summary` gains `prompt_flags`)
- Modify: `app/src/text2query/benchmark/benchmarking.py:243` (pass flags to manifest + summary)
- Modify: `app/tests/conftest.py` (remove PROMPT_TEMPLATE_PATH block), `app/tests/test_session_manifest.py`, `app/tests/test_reporting.py` (new param)
- Delete: `app/src/text2query/llm/prompt_loader.py`, `app/tests/test_prompt_loader.py`, `prompts/sql_generation.txt` (and the now-empty `prompts/` dir)
- Modify: `compose.yml` + `compose.yml.example` (remove `PROMPT_TEMPLATE_PATH` and the two `./prompts` volume mounts on `app` and `benchmark` services)

**Interfaces:**
- Produces: `PromptFlags` frozen dataclass (fields: `schema_ddl, schema_fk, schema_descriptions, schema_samples, xml_structure: bool`, `few_shot: int`, `planning, strict_output, retry_on_error: bool` — all default falsy) and module-level `PROMPT_FLAGS: PromptFlags` in `core/config.py`.
- Produces: `build_prompt(flags: PromptFlags, schema_str: str, question: str) -> str` in `llm/prompt_builder.py`.
- Produces: `write_session_manifest(..., prompt_flags: dict)` and `format_run_summary(..., prompt_flags: dict)`.

- [ ] **Step 1: Write failing tests for flags + baseline prompt**

`app/tests/test_prompt_builder.py`:

```python
from dataclasses import replace

from text2query.core.config import PromptFlags
from text2query.llm.prompt_builder import build_prompt

BASELINE = PromptFlags()

EXPECTED_BASELINE = """You are a PostgreSQL query generator used for SQL-generation benchmarking.

Given the following database schema:
Table 'singer': name (VARCHAR)

Generate a query to answer: How many singers are there?

Use PostgreSQL syntax. Only use tables and columns from the schema above."""


def test_all_flags_default_off():
    flags = PromptFlags()
    assert flags == PromptFlags(
        schema_ddl=False, schema_fk=False, schema_descriptions=False,
        schema_samples=False, xml_structure=False, few_shot=0,
        planning=False, strict_output=False, retry_on_error=False,
    )


def test_baseline_prompt_pinned_verbatim():
    prompt = build_prompt(BASELINE, "Table 'singer': name (VARCHAR)", "How many singers are there?")
    assert prompt == EXPECTED_BASELINE


def test_flags_are_frozen():
    import dataclasses, pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        BASELINE.schema_ddl = True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd app && uv run pytest tests/test_prompt_builder.py -q`
Expected: FAIL — `ImportError: cannot import name 'PromptFlags'`

- [ ] **Step 3: Implement PromptFlags in config.py**

Append to `app/src/text2query/core/config.py`:

```python
from dataclasses import dataclass


def _bool(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class PromptFlags:
    """Togglable prompt-engineering features. All-off = experimental baseline."""
    schema_ddl: bool = False
    schema_fk: bool = False
    schema_descriptions: bool = False
    schema_samples: bool = False
    xml_structure: bool = False
    few_shot: int = 0  # 0 = off; clamped to [0, 3] (research: >3 degrades <10B models)
    planning: bool = False
    strict_output: bool = False
    retry_on_error: bool = False


PROMPT_FLAGS = PromptFlags(
    schema_ddl=_env("PROMPT_SCHEMA_DDL", False, _bool),
    schema_fk=_env("PROMPT_SCHEMA_FK", False, _bool),
    schema_descriptions=_env("PROMPT_SCHEMA_DESCRIPTIONS", False, _bool),
    schema_samples=_env("PROMPT_SCHEMA_SAMPLES", False, _bool),
    xml_structure=_env("PROMPT_XML_STRUCTURE", False, _bool),
    few_shot=max(0, min(3, _env("PROMPT_FEW_SHOT", 0, int))),
    planning=_env("PROMPT_PLANNING", False, _bool),
    strict_output=_env("PROMPT_STRICT_OUTPUT", False, _bool),
    retry_on_error=_env("RETRY_ON_ERROR", False, _bool),
)
```

Also delete the `PROMPT_TEMPLATE_PATH` line from config.py.

- [ ] **Step 4: Implement the builder**

`app/src/text2query/llm/prompt_builder.py`:

```python
"""Assembles the SQL-generation prompt from togglable sections.

Section order is fixed (salience order from the thesis research): role,
schema, examples, planning, question, rules. Flags add/remove/reshape
sections; they never reorder them.
"""
from text2query.core.config import PromptFlags

_ROLE = "You are a PostgreSQL query generator used for SQL-generation benchmarking."

_RULES_MINIMAL = "Use PostgreSQL syntax. Only use tables and columns from the schema above."


def build_prompt(flags: PromptFlags, schema_str: str, question: str) -> str:
    sections = [
        _ROLE,
        f"Given the following database schema:\n{schema_str}",
        f"Generate a query to answer: {question}",
        _RULES_MINIMAL,
    ]
    return "\n\n".join(sections)
```

(Feature branches land one per task; this is deliberately the minimal baseline.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd app && uv run pytest tests/test_prompt_builder.py -q`
Expected: 3 passed

- [ ] **Step 6: Switch all callers off prompt_loader**

`app/src/text2query/llm/ollama.py` — replace the import and the prompt line:

```python
# old
from text2query.llm.prompt_loader import get_prompt_template, render_prompt
# new
from text2query.core.config import PROMPT_FLAGS  # add to existing config import line
from text2query.llm.prompt_builder import build_prompt
```

and in `generate_sql`, add an optional `flags` parameter (testability — global stays out of the builder):

```python
def generate_sql(
    user_query: str,
    schema_str: str,
    model: str | None = None,
    seed: int | None = None,
    flags=None,
) -> GenerationResult:
    selected_model = model or DEFAULT_MODEL
    prompt = build_prompt(flags or PROMPT_FLAGS, schema_str, user_query)
```

`app/src/text2query/server/main.py` — delete line 14 (`from text2query.llm.prompt_loader import get_prompt_template`) and line 104 (`get_prompt_template()  # fail fast...`).

`app/src/text2query/benchmark/runner.py` — replace the prompt_loader import with:

```python
from text2query.core.config import PROMPT_FLAGS
from text2query.llm.prompt_builder import build_prompt
```

and in `_run_single_generation`, the fingerprint becomes the **built skeleton** (sentinel placeholders keep it question-independent):

```python
    fingerprint = GenerationFingerprint(
        model=model,
        prompt_template=build_prompt(PROMPT_FLAGS, "{schema}", "{query}"),
        schema=schema,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        seed=seed,
    )
```

Delete: `app/src/text2query/llm/prompt_loader.py`, `app/tests/test_prompt_loader.py`, `prompts/sql_generation.txt`, then `rmdir prompts`.

`app/tests/conftest.py` — delete the whole `os.environ.setdefault("PROMPT_TEMPLATE_PATH", ...)` block and its comment (keep the file if other fixtures exist; if it becomes empty imports only, leave the empty file).

`compose.yml` **and** `compose.yml.example` — delete the `PROMPT_TEMPLATE_PATH` entry (and its comment lines) from `x-config`, and delete the `- ./prompts:/app/prompts:ro,Z` volume line from both the `app` and `benchmark` services.

- [ ] **Step 7: Record flags in session manifest and run summary**

`app/src/text2query/benchmark/reporting.py`:

- `write_session_manifest` (line 368): add keyword param `prompt_flags: dict` and add `"prompt_flags": prompt_flags,` to the manifest dict (right after `"generation_parameters"`).
- `format_run_summary` (line 402): add keyword param `prompt_flags: dict` and, after the `Seeds per query` line, add:

```python
    enabled = [
        (f"{k}={v}" if not isinstance(v, bool) else k)
        for k, v in prompt_flags.items()
        if v
    ]
    lines.append(f"  - Prompt features:     {', '.join(enabled) if enabled else 'none (baseline)'}")
```

`app/src/text2query/benchmark/benchmarking.py`: import `PROMPT_FLAGS` from config and `asdict` (already imported? if not: `from dataclasses import asdict`), then pass `prompt_flags=asdict(PROMPT_FLAGS)` to **both** the `write_session_manifest(...)` call (line ~243) and the `format_run_summary(...)` call below it.

Update `app/tests/test_session_manifest.py` and `app/tests/test_reporting.py`: existing calls to these two functions need the new `prompt_flags={}` (or a sample dict) argument; add one assertion that a passed dict lands under `"prompt_flags"` in the written manifest.

- [ ] **Step 8: Full test suite**

Run: `cd app && uv run pytest tests/ -q`
Expected: all pass (prompt_loader tests are gone; no other test may reference `PROMPT_TEMPLATE_PATH` — grep to confirm: `grep -rn PROMPT_TEMPLATE_PATH app/ compose*`  → no hits).

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: replace file prompt template with togglable prompt builder (all-off baseline)"
```

- [ ] **Step 10: USER GATE — baseline benchmark**

User rebuilds (`docker compose build app benchmark`) and runs a baseline benchmark (all flags unset). This anchors all later comparisons. Wait for explicit confirmation.

---

### Task 1: `PROMPT_STRICT_OUTPUT` — emphatic output rules

**Files:**
- Modify: `app/src/text2query/llm/prompt_builder.py`
- Test: `app/tests/test_prompt_builder.py`
- Modify: `compose.yml` + `compose.yml.example` (add env var)

**Interfaces:**
- Consumes: `PromptFlags.strict_output`, `build_prompt` from Task 0.
- Produces: rules section text used verbatim by later tests.

- [ ] **Step 1: Write failing test**

```python
def test_strict_output_appends_emphatic_rules():
    flags = replace(BASELINE, strict_output=True)
    prompt = build_prompt(flags, "S", "Q")
    assert prompt.endswith(
        "Use PostgreSQL syntax. Only use tables and columns from the schema above.\n"
        "Return ONLY the SQL query, nothing else.\n"
        "No explanations, no comments, no markdown."
    )
    assert "Return ONLY" not in build_prompt(BASELINE, "S", "Q")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd app && uv run pytest tests/test_prompt_builder.py -q` — Expected: FAIL (baseline has no strict block)

- [ ] **Step 3: Implement**

In `prompt_builder.py` add a constant and make the rules section conditional:

```python
_RULES_STRICT = (
    "Return ONLY the SQL query, nothing else.\n"
    "No explanations, no comments, no markdown."
)
```

and in `build_prompt`, replace the `_RULES_MINIMAL` list item with:

```python
        _RULES_MINIMAL + (f"\n{_RULES_STRICT}" if flags.strict_output else ""),
```

- [ ] **Step 4: Run tests** — `cd app && uv run pytest tests/test_prompt_builder.py -q` — Expected: PASS (baseline pin unchanged)

- [ ] **Step 5: Add env var to compose (both files), commit**

In `x-config` of `compose.yml` and `compose.yml.example`, start a features block:

```yaml
  # --- Prompt features (all default "false"/"0" = research baseline) --------
  PROMPT_STRICT_OUTPUT: "false" # Emphatic "Return ONLY the SQL query" rules block
```

```bash
git add -A && git commit -m "feat: add PROMPT_STRICT_OUTPUT toggle for emphatic output rules"
```

- [ ] **Step 6: USER GATE** — user benchmarks with `PROMPT_STRICT_OUTPUT: "true"`, confirms.

---

### Task 2: `PROMPT_SCHEMA_DDL` — CREATE TABLE schema rendering

**Files:**
- Modify: `app/src/text2query/database/schema.py` (add `render_schema`, `_render_ddl`, `_render_prose`; delete `get_database_schema_string`)
- Modify: `app/src/text2query/server/main.py:103`, `app/src/text2query/benchmark/runner.py` (switch callers)
- Test: `app/tests/test_schema_render.py` (new)
- Modify: `compose.yml` + `compose.yml.example`

**Interfaces:**
- Produces: `render_schema(engine, flags: PromptFlags, metadata: dict | None = None) -> str`. Prose mode (default) must reproduce today's `get_database_schema_string` output exactly (including FK notation — the FK flag takes over in Task 3).
- Consumes: `PromptFlags` from Task 0.

- [ ] **Step 1: Write failing tests** (SQLite in-memory engine — SQLAlchemy inspector works the same)

`app/tests/test_schema_render.py`:

```python
from sqlalchemy import create_engine, text

from text2query.core.config import PromptFlags
from text2query.database.schema import render_schema


def _engine():
    e = create_engine("sqlite://")
    with e.begin() as c:
        c.execute(text("CREATE TABLE orders (o_orderkey INTEGER PRIMARY KEY, o_status CHAR(1))"))
        c.execute(text(
            "CREATE TABLE lineitem (l_orderkey INTEGER REFERENCES orders(o_orderkey), "
            "l_qty DECIMAL)"
        ))
    return e


def test_prose_mode_matches_legacy_format():
    out = render_schema(_engine(), PromptFlags())
    assert "Table 'orders': o_orderkey (INTEGER), o_status (CHAR(1))" in out
    assert "FK(l_orderkey) -> orders" in out  # legacy FK notation kept until Task 3


def test_ddl_mode_emits_create_table():
    out = render_schema(_engine(), PromptFlags(schema_ddl=True))
    assert "CREATE TABLE orders (" in out
    assert "o_orderkey INTEGER" in out
    assert "PRIMARY KEY (o_orderkey)" in out
    assert "REFERENCES" not in out  # FK is a separate flag (Task 3)
```

- [ ] **Step 2: Run to verify failure** — `cd app && uv run pytest tests/test_schema_render.py -q` — Expected: FAIL, `cannot import name 'render_schema'`

- [ ] **Step 3: Implement in `database/schema.py`** (replace `get_database_schema_string` entirely):

```python
from sqlalchemy import create_engine, inspect, text

from text2query.core.config import PromptFlags


def render_schema(engine, flags: PromptFlags, metadata: dict | None = None) -> str:
    """Render the DB schema for the prompt, shaped by the schema feature flags."""
    inspector = inspect(engine)
    meta = metadata or {}
    if flags.schema_ddl:
        return _render_ddl(inspector, flags, meta)
    return _render_prose(inspector, flags, meta)


def _column_comment(table_meta: dict, col_name: str, flags: PromptFlags) -> str:
    """Enrichment text for one column ('' when flags/metadata provide nothing)."""
    info = table_meta.get(col_name, {})
    parts = []
    if flags.schema_descriptions and info.get("desc"):
        parts.append(info["desc"])
    if flags.schema_samples and info.get("samples"):
        parts.append("values: " + ", ".join(info["samples"]))
    return "; ".join(parts)


def _render_prose(inspector, flags: PromptFlags, meta: dict) -> str:
    lines = []
    for table in inspector.get_table_names():
        table_meta = meta.get(table, {})
        cols = []
        for c in inspector.get_columns(table):
            part = f"{c['name']} ({c['type']})"
            comment = _column_comment(table_meta, c["name"], flags)
            if comment:
                part += f" [{comment}]"
            cols.append(part)
        line = f"Table '{table}': {', '.join(cols)}"
        fks = [f"FK({','.join(fk['constrained_columns'])}) -> {fk['referred_table']}"
               for fk in inspector.get_foreign_keys(table)]
        if fks:
            line += f". {' '.join(fks)}"
        lines.append(line)
    return "\n".join(lines)


def _render_ddl(inspector, flags: PromptFlags, meta: dict) -> str:
    stmts = []
    for table in inspector.get_table_names():
        table_meta = meta.get(table, {})
        entries = []
        for c in inspector.get_columns(table):
            decl = f"{c['name']} {c['type']}"
            entries.append((decl, _column_comment(table_meta, c["name"], flags)))
        pk = inspector.get_pk_constraint(table).get("constrained_columns") or []
        if pk:
            entries.append((f"PRIMARY KEY ({', '.join(pk)})", ""))
        lines = []
        for i, (decl, comment) in enumerate(entries):
            comma = "," if i < len(entries) - 1 else ""
            suffix = f" -- {comment}" if comment else ""
            lines.append(f"  {decl}{comma}{suffix}")
        stmts.append(f"CREATE TABLE {table} (\n" + "\n".join(lines) + "\n);")
    return "\n\n".join(stmts)
```

Note: `_render_prose` keeps FK notation unconditional here — Task 3 puts it behind `flags.schema_fk`. `_column_comment` already handles descriptions/samples so Tasks 4–5 only add data + flag plumbing.

- [ ] **Step 4: Switch callers**

- `server/main.py` `AppContext.__init__`: `self.schema = render_schema(self.engine, PROMPT_FLAGS)` (import `render_schema` instead of `get_database_schema_string`, import `PROMPT_FLAGS` from config).
- `benchmark/runner.py` `_run_single_generation`: `schema = render_schema(engine, PROMPT_FLAGS)` (same import swap).
- Grep for stragglers: `grep -rn get_database_schema_string app/` — update any test that used it (`test_multi_seed.py`, `test_benchmark_caching.py` per earlier grep) to `render_schema(engine, PromptFlags())`.

- [ ] **Step 5: Full suite** — `cd app && uv run pytest tests/ -q` — Expected: all pass

- [ ] **Step 6: Compose + commit**

Add to the features block in both compose files:

```yaml
  PROMPT_SCHEMA_DDL: "false" # Schema as CREATE TABLE DDL instead of prose
```

```bash
git add -A && git commit -m "feat: add PROMPT_SCHEMA_DDL toggle for CREATE TABLE schema rendering"
```

- [ ] **Step 7: USER GATE** — benchmark with `PROMPT_SCHEMA_DDL: "true"`, confirm.

---

### Task 3: `PROMPT_SCHEMA_FK` — explicit foreign-key annotations

**Files:**
- Modify: `app/src/text2query/database/schema.py`
- Test: `app/tests/test_schema_render.py`
- Modify: `compose.yml` + `compose.yml.example`

**Interfaces:**
- Consumes: `render_schema`/`_render_prose`/`_render_ddl` from Task 2.
- Note: this task **changes the all-off baseline** — prose mode without the flag now drops the legacy FK notation (spec §3: today's behavior becomes an ablatable enriched state). Fingerprint auto-invalidates via the schema string.

- [ ] **Step 1: Write failing tests**

```python
def test_fk_flag_controls_prose_fk_notation():
    assert "FK(" not in render_schema(_engine(), PromptFlags())
    assert "FK(l_orderkey) -> orders" in render_schema(_engine(), PromptFlags(schema_fk=True))


def test_fk_flag_adds_references_in_ddl():
    out = render_schema(_engine(), PromptFlags(schema_ddl=True, schema_fk=True))
    assert "l_orderkey INTEGER REFERENCES orders(o_orderkey)" in out
```

Also update `test_prose_mode_matches_legacy_format` from Task 2: change its FK assertion to use `PromptFlags(schema_fk=True)`.

- [ ] **Step 2: Run to verify failure** — Expected: FAIL (`FK(` present at baseline; no `REFERENCES` in DDL)

- [ ] **Step 3: Implement**

In `_render_prose`, wrap the FK block:

```python
        if flags.schema_fk:
            fks = [f"FK({','.join(fk['constrained_columns'])}) -> {fk['referred_table']}"
                   for fk in inspector.get_foreign_keys(table)]
            if fks:
                line += f". {' '.join(fks)}"
```

In `_render_ddl`, before the column loop:

```python
        fk_targets: dict[str, str] = {}
        if flags.schema_fk:
            for fk in inspector.get_foreign_keys(table):
                for src, dst in zip(fk["constrained_columns"], fk["referred_columns"]):
                    fk_targets[src] = f"{fk['referred_table']}({dst})"
```

and in the loop, after `decl = f"{c['name']} {c['type']}"`:

```python
            if c["name"] in fk_targets:
                decl += f" REFERENCES {fk_targets[c['name']]}"
```

- [ ] **Step 4: Full suite** — `cd app && uv run pytest tests/ -q` — Expected: all pass

- [ ] **Step 5: Compose + commit**

```yaml
  PROMPT_SCHEMA_FK: "false" # Explicit FK annotations (REFERENCES in DDL, FK() notation in prose)
```

```bash
git add -A && git commit -m "feat: add PROMPT_SCHEMA_FK toggle for foreign-key annotations"
```

- [ ] **Step 6: USER GATE** — benchmark (suggest `PROMPT_SCHEMA_DDL+PROMPT_SCHEMA_FK` and FK-alone), confirm.

---

### Task 4: `PROMPT_SCHEMA_DESCRIPTIONS` — curated TPC-H column descriptions

**Files:**
- Create: `app/src/text2query/database/tpch_metadata.json` (full content below — packaged next to schema.py so the app container has it without new mounts; deviates from spec's `db/` location for exactly that reason)
- Modify: `app/src/text2query/database/schema.py` (add `load_tpch_metadata`)
- Modify: `app/src/text2query/server/main.py`, `app/src/text2query/benchmark/runner.py` (pass metadata)
- Test: `app/tests/test_schema_render.py`, `app/tests/test_tpch_metadata.py` (new)
- Modify: `compose.yml` + `compose.yml.example`

**Interfaces:**
- Produces: `load_tpch_metadata() -> dict` (cached; `{table: {column: {"desc": str, "samples": [str, ...]}}}` — `samples` optional per column, consumed in Task 5).
- Consumes: `_column_comment` from Task 2 (already reads `desc` when `flags.schema_descriptions`).

- [ ] **Step 1: Write failing tests**

```python
# in test_schema_render.py
def test_descriptions_flag_appends_comment_from_metadata():
    meta = {"orders": {"o_status": {"desc": "order status flag"}}}
    out = render_schema(_engine(), PromptFlags(schema_descriptions=True), metadata=meta)
    assert "o_status (CHAR(1)) [order status flag]" in out
    out_off = render_schema(_engine(), PromptFlags(), metadata=meta)
    assert "order status flag" not in out_off


def test_unknown_columns_degrade_gracefully():
    out = render_schema(_engine(), PromptFlags(schema_descriptions=True), metadata={})
    assert "[" not in out  # no enrichment markers at all
```

`app/tests/test_tpch_metadata.py`:

```python
from text2query.database.schema import load_tpch_metadata

TPCH_COLUMN_PREFIX = {
    "region": "r_", "nation": "n_", "supplier": "s_", "customer": "c_",
    "part": "p_", "partsupp": "ps_", "orders": "o_", "lineitem": "l_",
}


def test_metadata_covers_all_eight_tpch_tables():
    meta = load_tpch_metadata()
    assert set(meta) == set(TPCH_COLUMN_PREFIX)


def test_metadata_keys_look_like_real_tpch_columns():
    meta = load_tpch_metadata()
    for table, cols in meta.items():
        for col, info in cols.items():
            assert col.startswith(TPCH_COLUMN_PREFIX[table]), f"{table}.{col}"
            assert info.get("desc"), f"{table}.{col} missing desc"
```

- [ ] **Step 2: Run to verify failure** — Expected: FAIL, `cannot import name 'load_tpch_metadata'`

- [ ] **Step 3: Create the metadata file**

`app/src/text2query/database/tpch_metadata.json` (complete; `samples` keys are consumed in Task 5 but authored now):

```json
{
  "region": {
    "r_regionkey": {"desc": "unique region identifier"},
    "r_name": {"desc": "region name", "samples": ["'AFRICA'", "'AMERICA'", "'ASIA'"]},
    "r_comment": {"desc": "free-text comment"}
  },
  "nation": {
    "n_nationkey": {"desc": "unique nation identifier"},
    "n_name": {"desc": "nation name", "samples": ["'FRANCE'", "'GERMANY'", "'CHINA'"]},
    "n_regionkey": {"desc": "region this nation belongs to (joins region)"},
    "n_comment": {"desc": "free-text comment"}
  },
  "supplier": {
    "s_suppkey": {"desc": "unique supplier identifier"},
    "s_name": {"desc": "supplier name"},
    "s_address": {"desc": "supplier street address"},
    "s_nationkey": {"desc": "supplier's nation (joins nation)"},
    "s_phone": {"desc": "supplier phone number"},
    "s_acctbal": {"desc": "supplier account balance"},
    "s_comment": {"desc": "free-text comment"}
  },
  "customer": {
    "c_custkey": {"desc": "unique customer identifier"},
    "c_name": {"desc": "customer name"},
    "c_address": {"desc": "customer street address"},
    "c_nationkey": {"desc": "customer's nation (joins nation)"},
    "c_phone": {"desc": "customer phone number"},
    "c_acctbal": {"desc": "customer account balance"},
    "c_mktsegment": {"desc": "market segment", "samples": ["'BUILDING'", "'AUTOMOBILE'", "'MACHINERY'"]},
    "c_comment": {"desc": "free-text comment"}
  },
  "part": {
    "p_partkey": {"desc": "unique part identifier"},
    "p_name": {"desc": "part name (color/material words)"},
    "p_mfgr": {"desc": "manufacturer", "samples": ["'Manufacturer#1'", "'Manufacturer#5'"]},
    "p_brand": {"desc": "brand", "samples": ["'Brand#13'", "'Brand#42'"]},
    "p_type": {"desc": "part type string", "samples": ["'ECONOMY ANODIZED STEEL'", "'STANDARD POLISHED COPPER'"]},
    "p_size": {"desc": "part size (integer)"},
    "p_container": {"desc": "container type", "samples": ["'SM CASE'", "'JUMBO PKG'", "'MED BOX'"]},
    "p_retailprice": {"desc": "suggested retail price"},
    "p_comment": {"desc": "free-text comment"}
  },
  "partsupp": {
    "ps_partkey": {"desc": "part identifier (joins part)"},
    "ps_suppkey": {"desc": "supplier identifier (joins supplier)"},
    "ps_availqty": {"desc": "available quantity at this supplier"},
    "ps_supplycost": {"desc": "cost to supply this part"},
    "ps_comment": {"desc": "free-text comment"}
  },
  "orders": {
    "o_orderkey": {"desc": "unique order identifier"},
    "o_custkey": {"desc": "ordering customer (joins customer)"},
    "o_orderstatus": {"desc": "order status flag", "samples": ["'O' (open)", "'F' (fulfilled)", "'P' (partial)"]},
    "o_totalprice": {"desc": "total order price"},
    "o_orderdate": {"desc": "date the order was placed"},
    "o_orderpriority": {"desc": "order priority", "samples": ["'1-URGENT'", "'3-MEDIUM'", "'5-LOW'"]},
    "o_clerk": {"desc": "clerk who processed the order"},
    "o_shippriority": {"desc": "shipping priority (integer)"},
    "o_comment": {"desc": "free-text comment"}
  },
  "lineitem": {
    "l_orderkey": {"desc": "owning order (joins orders)"},
    "l_partkey": {"desc": "part ordered (joins part/partsupp)"},
    "l_suppkey": {"desc": "supplier of this line (joins supplier/partsupp)"},
    "l_linenumber": {"desc": "line number within the order"},
    "l_quantity": {"desc": "quantity ordered"},
    "l_extendedprice": {"desc": "extended price (quantity * part price)"},
    "l_discount": {"desc": "discount fraction", "samples": ["0.00", "0.05", "0.10"]},
    "l_tax": {"desc": "tax fraction"},
    "l_returnflag": {"desc": "return flag", "samples": ["'R' (returned)", "'A' (accepted)", "'N' (none)"]},
    "l_linestatus": {"desc": "line status flag", "samples": ["'O' (open)", "'F' (fulfilled)"]},
    "l_shipdate": {"desc": "date the line shipped"},
    "l_commitdate": {"desc": "committed delivery date"},
    "l_receiptdate": {"desc": "date the customer received the line"},
    "l_shipinstruct": {"desc": "shipping instructions", "samples": ["'DELIVER IN PERSON'", "'COLLECT COD'", "'NONE'"]},
    "l_shipmode": {"desc": "shipping mode", "samples": ["'AIR'", "'RAIL'", "'TRUCK'"]},
    "l_comment": {"desc": "free-text comment"}
  }
}
```

- [ ] **Step 4: Add the loader to `database/schema.py`**

```python
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_tpch_metadata() -> dict:
    """Curated TPC-H column descriptions/samples, packaged with the app."""
    return json.loads(Path(__file__).with_name("tpch_metadata.json").read_text(encoding="utf-8"))
```

Wire the callers: in `server/main.py` and `benchmark/runner.py`, the `render_schema(...)` calls gain `metadata=load_tpch_metadata()`.

Packaging check: the build backend is setuptools (`app/pyproject.toml` line 3). Add to `app/pyproject.toml`:

```toml
[tool.setuptools.package-data]
text2query = ["database/*.json"]
```

Verify with `cd app && uv run python -c "from text2query.database.schema import load_tpch_metadata; print(len(load_tpch_metadata()))"` — expected output: `8`.

- [ ] **Step 5: Full suite** — `cd app && uv run pytest tests/ -q` — Expected: all pass

- [ ] **Step 6: Compose + commit**

```yaml
  PROMPT_SCHEMA_DESCRIPTIONS: "false" # NL column descriptions from curated TPC-H metadata
```

```bash
git add -A && git commit -m "feat: add PROMPT_SCHEMA_DESCRIPTIONS toggle with curated TPC-H metadata"
```

- [ ] **Step 7: USER GATE** — benchmark with descriptions on, confirm.

---

### Task 5: `PROMPT_SCHEMA_SAMPLES` — inline sample values

**Files:**
- Test: `app/tests/test_schema_render.py`
- Modify: `compose.yml` + `compose.yml.example`
- (No renderer change expected — `_column_comment` from Task 2 already reads `samples` when `flags.schema_samples`; this task proves it and wires the env var.)

- [ ] **Step 1: Write failing-or-passing test (verify behavior exists)**

```python
def test_samples_flag_appends_values():
    meta = {"orders": {"o_status": {"desc": "status", "samples": ["'O' (open)", "'F' (fulfilled)"]}}}
    out = render_schema(_engine(), PromptFlags(schema_samples=True), metadata=meta)
    assert "values: 'O' (open), 'F' (fulfilled)" in out
    assert "values:" not in render_schema(_engine(), PromptFlags(), metadata=meta)


def test_desc_and_samples_combine_with_semicolon():
    meta = {"orders": {"o_status": {"desc": "status", "samples": ["'O'"]}}}
    out = render_schema(
        _engine(), PromptFlags(schema_descriptions=True, schema_samples=True), metadata=meta
    )
    assert "[status; values: 'O']" in out
```

- [ ] **Step 2: Run** — `cd app && uv run pytest tests/test_schema_render.py -q` — Expected: PASS already (implementation landed generically in Task 2). If it fails, fix `_column_comment` until it passes — do not restructure.

- [ ] **Step 3: Compose + commit**

```yaml
  PROMPT_SCHEMA_SAMPLES: "false" # Inline sample values for categorical columns
```

```bash
git add -A && git commit -m "feat: add PROMPT_SCHEMA_SAMPLES toggle for inline categorical values"
```

- [ ] **Step 4: USER GATE** — benchmark with samples on, confirm.

---

### Task 6: `PROMPT_XML_STRUCTURE` — XML-tagged sections

**Files:**
- Modify: `app/src/text2query/llm/prompt_builder.py`
- Test: `app/tests/test_prompt_builder.py`
- Modify: `compose.yml` + `compose.yml.example`

**Interfaces:**
- Produces: tag names `<schema>`, `<examples>`, `<rules>`, `<query>` (role and planning untagged; examples tag appears in Task 7).

- [ ] **Step 1: Write failing test**

```python
def test_xml_structure_wraps_sections_in_order():
    flags = replace(BASELINE, xml_structure=True)
    prompt = build_prompt(flags, "SCHEMA_TEXT", "QUESTION_TEXT")
    assert "<schema>\nGiven the following database schema:\nSCHEMA_TEXT\n</schema>" in prompt
    assert "<query>\nGenerate a query to answer: QUESTION_TEXT\n</query>" in prompt
    assert "<rules>\nUse PostgreSQL syntax" in prompt and prompt.rstrip().endswith("</rules>")
    assert prompt.index("<schema>") < prompt.index("<query>") < prompt.index("<rules>")
    assert "<" not in build_prompt(BASELINE, "S", "Q")  # baseline untouched
```

- [ ] **Step 2: Run to verify failure** — Expected: FAIL

- [ ] **Step 3: Implement**

Restructure `build_prompt` to tag-aware section tuples (this is the final shape later tasks extend):

```python
def _wrap(tag: str | None, body: str, xml: bool) -> str:
    if xml and tag:
        return f"<{tag}>\n{body}\n</{tag}>"
    return body


def build_prompt(flags: PromptFlags, schema_str: str, question: str) -> str:
    rules = _RULES_MINIMAL + (f"\n{_RULES_STRICT}" if flags.strict_output else "")
    sections: list[tuple[str | None, str]] = [
        (None, _ROLE),
        ("schema", f"Given the following database schema:\n{schema_str}"),
        ("query", f"Generate a query to answer: {question}"),
        ("rules", rules),
    ]
    return "\n\n".join(_wrap(tag, body, flags.xml_structure) for tag, body in sections)
```

- [ ] **Step 4: Run full builder tests** — Expected: PASS including the pinned baseline (all-off output is byte-identical to before)

- [ ] **Step 5: Compose + commit**

```yaml
  PROMPT_XML_STRUCTURE: "false" # Wrap prompt sections in XML tags (<schema>, <rules>, ...)
```

```bash
git add -A && git commit -m "feat: add PROMPT_XML_STRUCTURE toggle for XML-tagged prompt sections"
```

- [ ] **Step 6: USER GATE** — benchmark with XML on, confirm.

---

### Task 7: `PROMPT_FEW_SHOT` — static schema-agnostic examples

**Files:**
- Modify: `app/src/text2query/llm/prompt_builder.py`
- Test: `app/tests/test_prompt_builder.py`
- Modify: `compose.yml` + `compose.yml.example`

**Interfaces:**
- Produces: `FEW_SHOT_EXAMPLES: list[tuple[str, str]]` (3 pairs, deliberately non-TPC-H schemas to avoid context pull).

- [ ] **Step 1: Write failing tests**

```python
def test_few_shot_inserts_n_examples_between_schema_and_question():
    flags = replace(BASELINE, few_shot=2)
    prompt = build_prompt(flags, "S", "Q")
    assert prompt.count("Question:") == 2 and prompt.count("SQL:") == 2
    assert prompt.index("S") < prompt.index("Question:") < prompt.index("Generate a query")


def test_few_shot_zero_means_no_examples():
    assert "Question:" not in build_prompt(BASELINE, "S", "Q")


def test_few_shot_examples_avoid_tpch_tables():
    from text2query.llm.prompt_builder import FEW_SHOT_EXAMPLES
    tpch = ("lineitem", "orders", "customer", "supplier", "partsupp", "nation", "region")
    assert len(FEW_SHOT_EXAMPLES) == 3
    for _, sql in FEW_SHOT_EXAMPLES:
        assert not any(t in sql.lower() for t in tpch)
```

- [ ] **Step 2: Run to verify failure** — Expected: FAIL

- [ ] **Step 3: Implement**

Add to `prompt_builder.py`:

```python
# Static, schema-agnostic pairs (Spider-style; deliberately NOT TPC-H tables,
# so small models can't copy structure instead of reading the user's question).
FEW_SHOT_EXAMPLES: list[tuple[str, str]] = [
    (
        "How many singers are there?",
        "SELECT COUNT(*) FROM singer;",
    ),
    (
        "List each department's name and its number of employees, largest first.",
        "SELECT d.dept_name, COUNT(e.emp_id) AS num_employees\n"
        "FROM department d JOIN employee e ON e.dept_id = d.dept_id\n"
        "GROUP BY d.dept_name ORDER BY num_employees DESC;",
    ),
    (
        "Show the titles of courses with more students enrolled than the average enrollment.",
        "SELECT title FROM course\n"
        "WHERE enrollment > (SELECT AVG(enrollment) FROM course);",
    ),
]


def _examples_section(n: int) -> str:
    pairs = FEW_SHOT_EXAMPLES[:n]
    blocks = [f"Question: {q}\nSQL: {sql}" for q, sql in pairs]
    return "Example question-to-SQL conversions (from other databases):\n\n" + "\n\n".join(blocks)
```

Restructure `build_prompt` to build the section list imperatively so conditional sections land in their fixed slots (this is the complete function after this task):

```python
def build_prompt(flags: PromptFlags, schema_str: str, question: str) -> str:
    rules = _RULES_MINIMAL + (f"\n{_RULES_STRICT}" if flags.strict_output else "")
    sections: list[tuple[str | None, str]] = [
        (None, _ROLE),
        ("schema", f"Given the following database schema:\n{schema_str}"),
    ]
    if flags.few_shot > 0:
        sections.append(("examples", _examples_section(flags.few_shot)))
    sections.append(("query", f"Generate a query to answer: {question}"))
    sections.append(("rules", rules))
    return "\n\n".join(_wrap(tag, body, flags.xml_structure) for tag, body in sections)
```

- [ ] **Step 4: Run full builder tests** — Expected: PASS (baseline pin still byte-identical)

- [ ] **Step 5: Compose + commit**

```yaml
  PROMPT_FEW_SHOT: "0" # Static few-shot examples: 0=off, max 3 (values above 3 clamp)
```

```bash
git add -A && git commit -m "feat: add PROMPT_FEW_SHOT toggle with 3 static schema-agnostic examples"
```

- [ ] **Step 6: USER GATE** — benchmark at `PROMPT_FEW_SHOT: "3"` (and optionally "1"), confirm.

---

### Task 8: `PROMPT_PLANNING` — lightweight planning scaffold

**Files:**
- Modify: `app/src/text2query/llm/prompt_builder.py`
- Test: `app/tests/test_prompt_builder.py`
- Modify: `compose.yml` + `compose.yml.example`

- [ ] **Step 1: Write failing test**

```python
def test_planning_scaffold_between_examples_and_question():
    flags = replace(BASELINE, planning=True)
    prompt = build_prompt(flags, "S", "Q")
    assert "list the relevant tables and the join path as SQL comments" in prompt
    assert prompt.index("S") < prompt.index("join path") < prompt.index("Generate a query")
    assert "join path" not in build_prompt(BASELINE, "S", "Q")
```

- [ ] **Step 2: Run to verify failure** — Expected: FAIL

- [ ] **Step 3: Implement**

Add constant:

```python
_PLANNING = (
    "Before writing the query: list the relevant tables and the join path as SQL "
    "comments (lines starting with --). Then write the final SQL query."
)
```

In `build_prompt`, between the examples insertion and the query append (the complete middle of the function after this task):

```python
    if flags.few_shot > 0:
        sections.append(("examples", _examples_section(flags.few_shot)))
    if flags.planning:
        sections.append((None, _PLANNING))
    sections.append(("query", f"Generate a query to answer: {question}"))
```

(Untagged even under XML — it is an instruction, not a data block; the extractor `_clean_sql_response` in `llm/service.py` is deliberately unchanged, so extraction failures under this flag are a measured outcome, per spec.)

- [ ] **Step 4: Run full builder tests** — Expected: PASS

- [ ] **Step 5: Compose + commit**

```yaml
  PROMPT_PLANNING: "false" # Ask model to plan tables/joins as SQL comments before the query
```

```bash
git add -A && git commit -m "feat: add PROMPT_PLANNING toggle for lightweight planning scaffold"
```

- [ ] **Step 6: USER GATE** — benchmark with planning on, confirm.

---

### Task 9: `RETRY_ON_ERROR` — execution-guided single retry

**Files:**
- Modify: `app/src/text2query/llm/ollama.py` (extract `_generate`, add `generate_sql_with_retry`, extend `GenerationResult`)
- Modify: `app/src/text2query/database/executor.py` (add `explain_error`)
- Modify: `app/src/text2query/server/main.py:76-84` (`handle_query` uses retry + validator)
- Modify: `app/src/text2query/benchmark/runner.py` (use retry + validator, count retries, fingerprint field)
- Modify: `app/src/text2query/benchmark/fingerprint.py` (add `retry_on_error: bool = False`)
- Test: `app/tests/test_retry.py` (new)
- Modify: `compose.yml` + `compose.yml.example`

**Interfaces:**
- Produces: `generate_sql_with_retry(user_query, schema_str, model=None, seed=None, validate=None, flags=None) -> GenerationResult` where `validate: Callable[[str], str | None]` returns an error string or None.
- Produces: `GenerationResult.retried: bool = False`, `GenerationResult.retry_reason: str | None = None`.
- Produces: `explain_error(engine, sql: str) -> str | None` in `database/executor.py`.
- The llm layer must NOT import the database layer — callers build the validator.

- [ ] **Step 1: Write failing tests** (monkeypatch the transport; no DB, no Ollama)

`app/tests/test_retry.py`:

```python
from text2query.core.config import PromptFlags
from text2query.llm import ollama

RETRY_ON = PromptFlags(retry_on_error=True)


def _fake_transport(responses):
    """Return a _post_json stand-in yielding canned Ollama responses in order."""
    calls = []

    def fake(url, payload, timeout):
        calls.append(payload)
        return 200, {"response": responses[len(calls) - 1]}

    return fake, calls


def test_no_retry_when_flag_off(monkeypatch):
    fake, calls = _fake_transport(["SELECT 1;"])
    monkeypatch.setattr(ollama, "_post_json", fake)
    result = ollama.generate_sql_with_retry(
        "q", "s", flags=PromptFlags(), validate=lambda sql: "boom",
    )
    assert len(calls) == 1 and result.retried is False


def test_retry_on_validator_error_appends_error_text(monkeypatch):
    fake, calls = _fake_transport(["SELECT bad;", "SELECT good;"])
    monkeypatch.setattr(ollama, "_post_json", fake)
    result = ollama.generate_sql_with_retry(
        "q", "s", flags=RETRY_ON,
        validate=lambda sql: 'column "bad" does not exist' if "bad" in sql else None,
    )
    assert len(calls) == 2
    assert 'column "bad" does not exist' in calls[1]["prompt"]
    assert result.retried is True and result.sql == "SELECT good;"


def test_retry_on_extraction_failure(monkeypatch):
    fake, calls = _fake_transport(["I cannot write SQL, sorry!", "SELECT 1;"])
    monkeypatch.setattr(ollama, "_post_json", fake)
    result = ollama.generate_sql_with_retry("q", "s", flags=RETRY_ON, validate=None)
    assert len(calls) == 2 and result.retried is True and result.sql == "SELECT 1;"


def test_no_second_retry(monkeypatch):
    fake, calls = _fake_transport(["SELECT bad;", "SELECT still_bad;"])
    monkeypatch.setattr(ollama, "_post_json", fake)
    result = ollama.generate_sql_with_retry(
        "q", "s", flags=RETRY_ON, validate=lambda sql: "always broken",
    )
    assert len(calls) == 2  # exactly one retry, result returned as-is
    assert result.retried is True
```

Note: the two happy-path canned responses end with `;` so the existing extractor regex (`(SELECT|WITH)\s+.*?;`) finds them.

- [ ] **Step 2: Run to verify failure** — Expected: FAIL, no `generate_sql_with_retry`

- [ ] **Step 3: Implement**

`app/src/text2query/llm/ollama.py`:

1. Extend the dataclass:

```python
@dataclass
class GenerationResult:
    """Result of a single SQL-generation call."""

    sql: str | None
    raw_response: str | None = None
    prompt: str | None = None
    error: str | None = None
    retried: bool = False
    retry_reason: str | None = None
```

2. Extract the transport+parse body of `generate_sql` into `_generate(prompt, model, seed)` (everything from `options = {...}` down, unchanged); `generate_sql` becomes:

```python
def generate_sql(user_query, schema_str, model=None, seed=None, flags=None):
    selected_model = model or DEFAULT_MODEL
    prompt = build_prompt(flags or PROMPT_FLAGS, schema_str, user_query)
    return _generate(prompt, selected_model, seed)
```

3. Add:

```python
def generate_sql_with_retry(
    user_query: str,
    schema_str: str,
    model: str | None = None,
    seed: int | None = None,
    validate=None,
    flags=None,
) -> GenerationResult:
    """Single execution-guided retry: re-prompt once with the failure appended.

    `validate(sql)` returns an error string (fed back to the model) or None.
    Transport errors (timeout, 404) are returned as-is — feedback can't fix those.
    """
    flags = flags or PROMPT_FLAGS
    result = generate_sql(user_query, schema_str, model, seed=seed, flags=flags)
    if not flags.retry_on_error or result.error:
        return result

    if result.sql is None:
        reason = "Your previous answer contained no SQL query."
    elif validate is not None and (err := validate(result.sql)):
        reason = f"Your previous query failed with this PostgreSQL error: {err}"
    else:
        return result

    retry_prompt = (
        f"{result.prompt}\n\n"
        f"Your previous answer was:\n{result.raw_response}\n\n"
        f"{reason}\n"
        "Fix it. Return ONLY the corrected SQL query, no explanation, no markdown."
    )
    retried = _generate(retry_prompt, model or DEFAULT_MODEL, seed)
    retried.retried = True
    retried.retry_reason = reason
    return retried
```

`app/src/text2query/database/executor.py`:

```python
def explain_error(engine, sql: str) -> str | None:
    """Cheap validity probe: EXPLAIN surfaces syntax/schema errors without running the query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"EXPLAIN {sql}"))
        return None
    except Exception as e:
        return str(e)
```

`server/main.py` `handle_query` — replace the generate call:

```python
    result = llm.generate_sql_with_retry(
        question, schema, model, validate=lambda sql: explain_error(engine, sql),
    )
```

(import `explain_error` next to `execute_sql_query`).

`benchmark/runner.py` `_run_single_generation` — replace the generate call:

```python
        result = ollama.generate_sql_with_retry(
            question, schema, model, seed=seed,
            validate=lambda sql: explain_error(engine, sql),
        )
```

(import `explain_error` from `text2query.database.executor`), count retries alongside `success` (`retries = sum(...)` — increment when `result.retried`), and after the success print add:

```python
    if retries:
        print(f"  ↻ {retries} queries needed a retry")
```

`benchmark/fingerprint.py` — add field with default so existing tests/constructors keep working:

```python
    seed: int | None
    retry_on_error: bool = False
```

and in runner's fingerprint construction pass `retry_on_error=PROMPT_FLAGS.retry_on_error`.

- [ ] **Step 4: Full suite** — `cd app && uv run pytest tests/ -q` — Expected: all pass

- [ ] **Step 5: Compose + commit**

```yaml
  RETRY_ON_ERROR: "false" # One retry with the Postgres error fed back (EXPLAIN probe)
```

```bash
git add -A && git commit -m "feat: add RETRY_ON_ERROR execution-guided single-retry"
```

- [ ] **Step 6: USER GATE** — benchmark with retry on; report should show retry counts. Final feature — after confirmation the rollout is complete.

---

## Self-review notes (already applied)

- Spec §5 "echoed in the report header" is satisfied by the `format_run_summary` prompt-features line plus the manifest (Task 0 Step 7).
- Metadata file lives at `app/src/text2query/database/tpch_metadata.json`, not `db/` — spec deviation, reason: the app container has no `db/` mount and packaging beats adding one.
- Task 5 has no implementation step by design: Task 2's `_column_comment` is written generically; Task 5 proves the behavior with tests and wires the env var.
- The all-off baseline prompt is pinned verbatim in Task 0 and must remain byte-identical through Tasks 1–9 (the Task 6 restructure explicitly re-verifies it).
