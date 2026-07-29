# Benchmark Pipeline Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate print-based console narration from pipeline logic in `app/src/text2query/benchmark/`, decompose `benchmarking.py::main()` into named stages, backfill unit tests for the now-testable logic, and document the six-stage evaluation methodology in the README — per the approved design at `docs/superpowers/specs/2026-07-24-benchmark-pipeline-refactor-design.md`.

**Architecture:** Multi-step logic functions (`setup_database`) split along their existing print boundaries into narrower functions that return data instead of printing. Per-item progress loops (`_run_single_generation`, `execute_queries_to_csv`, `load_tpch_data`) take optional `on_item_start`/`on_item_done` callbacks defaulting to shared print-based renderers in a new `progress.py`, so tests can inject no-op/capturing callbacks and assert on returned data instead of stdout. `benchmarking.py::main()` gets three extractions (`_resolve_query_id_filter`, a `BenchmarkPaths` dataclass, `format_run_summary`) so it reads as a short, named sequence.

**Tech Stack:** Python 3.12, pytest, stdlib `unittest.mock`/`monkeypatch`. No new dependencies.

## Global Constraints

- No new dependencies — stdlib + existing `pandas`, `sqlalchemy`, `psycopg2-binary`, `sqlglot` only.
- Console output for a real benchmark run must stay byte-for-byte identical to today (this is why per-item loops use a two-call `on_item_start`/`on_item_done` callback rather than a single post-hoc print — the live "in progress" indicator during a slow LLM/DB call is preserved).
- No changes to `server/`, `llm/`, or `database/` — confirmed clean during design.
- No changes to CLI flags, env vars, or Docker Compose files.
- Test style matches existing `app/tests/`: small `test_*` functions, `tmp_path`/`monkeypatch` fixtures, `unittest.mock.patch` targeting module-qualified names, no new test framework.
- Run tests from the `app/` directory: `.venv/bin/python -m pytest tests/<file> -v`.

---

### Task 1: Shared progress-narration callbacks

**Files:**
- Create: `app/src/text2query/benchmark/progress.py`
- Test: `app/tests/test_progress.py`

**Interfaces:**
- Produces: `print_item_start(i: int, total: int, label: str) -> None` and `print_item_done(outcome: str) -> None` — imported by `pipeline.py`, `runner.py`, and `data_loader.py` in later tasks as default callback values.

- [ ] **Step 1: Write the failing test**

Create `app/tests/test_progress.py`:

```python
from text2query.benchmark.progress import print_item_done, print_item_start


def test_print_item_start_writes_label_without_newline(capsys):
    print_item_start(2, 5, "Q01")
    captured = capsys.readouterr()
    assert captured.out == "  [2/5] Q01..."


def test_print_item_done_completes_the_line(capsys):
    print_item_done(" ✓ (3 rows)")
    captured = capsys.readouterr()
    assert captured.out == " ✓ (3 rows)\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `app/`): `.venv/bin/python -m pytest tests/test_progress.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'text2query.benchmark.progress'`

- [ ] **Step 3: Write the implementation**

Create `app/src/text2query/benchmark/progress.py`:

```python
"""Default CLI progress-narration callbacks shared by benchmark pipeline stages."""


def print_item_start(i: int, total: int, label: str) -> None:
    """Print the start of a per-item progress line, without a trailing newline."""
    print(f"  [{i}/{total}] {label}...", end="", flush=True)


def print_item_done(outcome: str) -> None:
    """Complete a per-item progress line started by print_item_start."""
    print(outcome)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_progress.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/src/text2query/benchmark/progress.py app/tests/test_progress.py
git commit -m "feat: add shared progress-narration callbacks for benchmark stages"
```

---

### Task 2: Split `setup_database` into testable stages

**Files:**
- Modify: `app/src/text2query/benchmark/pipeline.py:122-176`
- Modify: `app/src/text2query/benchmark/benchmarking.py` (drop the now-unused `scale_factor` kwarg from the `setup_database` call)
- Test: `app/tests/test_setup_database.py`

**Interfaces:**
- Produces: `load_schema(schema_file: Path, db_url: str) -> None`, `load_data(data_dir: Path, db_url: str) -> dict[str, int]`, `build_indexes(schema_file: Path, db_url: str) -> bool` in `pipeline.py`. `setup_database(schema_file, data_dir, db_url) -> None` keeps its name but drops the unused `scale_factor` parameter.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_setup_database.py`:

```python
from pathlib import Path

import pytest

from text2query.benchmark.pipeline import build_indexes, load_data, load_schema


class _FakeConn:
    def __init__(self, executed):
        self._executed = executed

    def execute(self, stmt):
        self._executed.append(str(stmt))


class _FakeTxn:
    def __init__(self, executed):
        self._executed = executed

    def __enter__(self):
        return _FakeConn(self._executed)

    def __exit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self, executed):
        self._executed = executed

    def begin(self):
        return _FakeTxn(self._executed)


def test_load_schema_executes_each_statement(tmp_path, monkeypatch):
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE a (id int);\nCREATE TABLE b (id int);")
    executed = []
    monkeypatch.setattr(
        "text2query.benchmark.pipeline.create_engine_for_database",
        lambda url: _FakeEngine(executed),
    )

    load_schema(schema_file, "postgresql://fake")

    # First statement terminates other backends, then the two CREATE TABLEs
    assert len(executed) == 3
    assert "CREATE TABLE a" in executed[1]
    assert "CREATE TABLE b" in executed[2]


def test_load_schema_wraps_failures(tmp_path, monkeypatch):
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE a (id int);")

    class FailingEngine:
        def begin(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "text2query.benchmark.pipeline.create_engine_for_database", lambda url: FailingEngine()
    )

    with pytest.raises(RuntimeError, match="Failed to load schema"):
        load_schema(schema_file, "postgresql://fake")


def test_load_data_wraps_missing_files(tmp_path, monkeypatch):
    def fake_load(data_dir, db_url):
        raise FileNotFoundError("Missing .tbl files: region")

    monkeypatch.setattr("text2query.benchmark.pipeline.load_tpch_data", fake_load)

    with pytest.raises(RuntimeError, match="Failed to load data"):
        load_data(tmp_path, "postgresql://fake")


def test_load_data_returns_counts(monkeypatch):
    monkeypatch.setattr(
        "text2query.benchmark.pipeline.load_tpch_data",
        lambda data_dir, db_url: {"region": 5, "nation": 25},
    )

    counts = load_data(Path("unused"), "postgresql://fake")

    assert counts == {"region": 5, "nation": 25}


def test_build_indexes_returns_false_when_no_indexes_file(tmp_path):
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE a (id int);")

    assert build_indexes(schema_file, "postgresql://fake") is False


def test_build_indexes_executes_statements(tmp_path, monkeypatch):
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE a (id int);")
    (tmp_path / "indexes.sql").write_text("CREATE INDEX idx_a ON a (id);")
    executed = []
    monkeypatch.setattr(
        "text2query.benchmark.pipeline.create_engine_for_database",
        lambda url: _FakeEngine(executed),
    )

    built = build_indexes(schema_file, "postgresql://fake")

    assert built is True
    assert len(executed) == 1
    assert "CREATE INDEX idx_a" in executed[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_setup_database.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_schema'` (etc. — the functions don't exist yet)

- [ ] **Step 3: Replace `setup_database` in `pipeline.py`**

In `app/src/text2query/benchmark/pipeline.py`, replace the entire `setup_database` function (lines 122–176) with:

```python
def load_schema(schema_file: Path, db_url: str) -> None:
    """Load the TPC-H schema DDL, terminating other backends holding locks first."""
    statements = _parse_schema_sql(schema_file)
    engine = create_engine_for_database(db_url)

    try:
        with engine.begin() as conn:
            # Terminate other backends holding locks (e.g. app container's pool)
            conn.execute(text(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "  AND pid <> pg_backend_pid()"
            ))

            for statement in statements:
                conn.execute(text(statement))
    except Exception as e:
        raise RuntimeError(f"Failed to load schema: {e}")


def load_data(data_dir: Path, db_url: str) -> dict[str, int]:
    """Load TPC-H .tbl files into the database. Returns row counts per table."""
    try:
        return load_tpch_data(data_dir, db_url)
    except (FileNotFoundError, RuntimeError) as e:
        raise RuntimeError(f"Failed to load data: {e}")


def build_indexes(schema_file: Path, db_url: str) -> bool:
    """Build indexes from indexes.sql next to the schema file.

    Returns False (without error) if no indexes.sql exists — index creation
    is best-effort and non-fatal to the caller.
    """
    indexes_file = schema_file.parent / "indexes.sql"
    if not indexes_file.exists():
        return False

    engine = create_engine_for_database(db_url)
    indexes_sql = indexes_file.read_text()
    statements = [s.strip() for s in indexes_sql.split(";") if s.strip()]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
    return True


def setup_database(
    schema_file: Path,
    data_dir: Path,
    db_url: str,
) -> None:
    """Load schema, data, and indexes, narrating each step. Index failures are non-fatal."""
    print("  Loading database schema...")
    load_schema(schema_file, db_url)
    print("  ✓ Schema loaded")

    print("  Loading TPC-H data from .tbl files...")
    loaded_counts = load_data(data_dir, db_url)
    total_rows = sum(loaded_counts.values())
    print(f"  ✓ Loaded {total_rows:,} total rows into 8 tables")
    for table, count in sorted(loaded_counts.items()):
        print(f"    - {table}: {count:,} rows")

    print("  Building indexes...")
    try:
        built = build_indexes(schema_file, db_url)
    except Exception as e:
        print(f"  ⚠ Index creation failed (non-fatal): {e}")
    else:
        print("  ✓ Indexes built" if built else "  ⚠ No indexes.sql found, skipping index creation")
```

(The old signature took a now-unused `scale_factor: int` parameter — it was never referenced in the body. Dropped.)

- [ ] **Step 4: Update the call site in `benchmarking.py`**

In `app/src/text2query/benchmark/benchmarking.py`, find:

```python
            setup_database(
                schema_file=schema_file,
                data_dir=data_dir,
                db_url=DATABASE_URL,
                scale_factor=BENCHMARK_SCALE_FACTOR
            )
```

Replace with:

```python
            setup_database(
                schema_file=schema_file,
                data_dir=data_dir,
                db_url=DATABASE_URL,
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_setup_database.py -v`
Expected: 6 passed

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all previously-passing tests still pass (88 + new)

- [ ] **Step 7: Commit**

```bash
git add app/src/text2query/benchmark/pipeline.py app/src/text2query/benchmark/benchmarking.py app/tests/test_setup_database.py
git commit -m "refactor: split setup_database into load_schema/load_data/build_indexes"
```

---

### Task 3: Callback-driven progress in `execute_queries_to_csv`

**Files:**
- Modify: `app/src/text2query/benchmark/pipeline.py` (top imports + `execute_queries_to_csv`, lines 201–254)
- Modify: `app/tests/test_pipeline_helpers.py` (add a test to the existing `TestExecuteQueriesToCsv` class)

**Interfaces:**
- Consumes: `print_item_start`, `print_item_done` from `text2query.benchmark.progress` (Task 1).
- Produces: `execute_queries_to_csv(..., on_item_start=print_item_start, on_item_done=print_item_done)` — unchanged return type (`list[dict]`), unchanged default console output.

- [ ] **Step 1: Write the failing test**

In `app/tests/test_pipeline_helpers.py`, add this method inside the existing `TestExecuteQueriesToCsv` class (below `test_writes_error_file_on_failure_when_enabled`):

```python
    def test_invokes_item_callbacks_with_outcome(self, tmp_path, monkeypatch):
        import pandas as pd
        self._patch(monkeypatch, ExecutionResult(pd.DataFrame({"a": [1, 2]}), None))
        query_file = tmp_path / "01.sql"
        query_file.write_text("SELECT 1")
        output_dir = tmp_path / "answers"

        starts = []
        outcomes = []

        execute_queries_to_csv(
            [query_file], output_dir, "postgresql://fake",
            on_item_start=lambda i, total, label: starts.append((i, total, label)),
            on_item_done=lambda outcome: outcomes.append(outcome),
        )

        assert starts == [(1, 1, "Q01")]
        assert outcomes == [" ✓ (2 rows)"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline_helpers.py -v`
Expected: FAIL with `TypeError: execute_queries_to_csv() got an unexpected keyword argument 'on_item_start'`

- [ ] **Step 3: Update `execute_queries_to_csv` in `pipeline.py`**

Add to the top imports of `app/src/text2query/benchmark/pipeline.py`:

```python
from text2query.benchmark.progress import print_item_done, print_item_start
```

Replace the `execute_queries_to_csv` function (lines 201–254) with:

```python
def execute_queries_to_csv(
    query_files: list[Path],
    output_dir: Path,
    db_url: str,
    *,
    write_error_file: bool = False,
    on_item_start=print_item_start,
    on_item_done=print_item_done,
) -> list[dict]:
    """Execute SQL files and save results as CSV.

    Args:
        query_files: .sql files to execute
        output_dir: directory for .csv results
        db_url: database connection URL
        write_error_file: on failure, write the error message to a sidecar .error file
        on_item_start: called as (index, total, label) before each query executes
        on_item_done: called with the outcome text after each query executes
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine_for_database(db_url)
    results = []

    for i, query_file in enumerate(query_files, 1):
        query_id = query_file.stem
        on_item_start(i, len(query_files), f"Q{query_id}")

        try:
            sql = query_file.read_text().strip()
            result = execute_sql_query(engine, sql)

            if not result.ok:
                if write_error_file:
                    (output_dir / f"{query_id}.error").write_text(result.error)
                on_item_done(" ✗ (error)")
                results.append({"query_id": query_id, "status": "error", "error": result.error})
            else:
                output_file = output_dir / f"{query_id}.csv"
                result.data.to_csv(output_file, index=False)
                on_item_done(f" ✓ ({len(result.data)} rows)")
                results.append({"query_id": query_id, "status": "success", "rows": len(result.data)})

        except Exception as e:
            if write_error_file:
                (output_dir / f"{query_id}.error").write_text(str(e))
            on_item_done(" ✗ (error)")
            results.append({"query_id": query_id, "status": "error", "error": str(e)})

    success = sum(1 for r in results if r["status"] == "success")
    errors = sum(1 for r in results if r["status"] == "error")
    print(f"  ✓ Executed {success} queries -> {output_dir}")
    if errors > 0:
        print(f"  ⚠ {errors} failed:")
        for r in results:
            if r["status"] == "error":
                print(f"    - Q{r['query_id']}: {r.get('error', 'Unknown')[:60]}")

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pipeline_helpers.py -v`
Expected: 2 passed

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add app/src/text2query/benchmark/pipeline.py app/tests/test_pipeline_helpers.py
git commit -m "refactor: make execute_queries_to_csv progress narration injectable"
```

---

### Task 4: Callback-driven progress in `load_tpch_data`

**Files:**
- Modify: `app/src/text2query/benchmark/data_loader.py`
- Test: `app/tests/test_data_loader.py`

**Interfaces:**
- Consumes: `print_item_start`, `print_item_done` from `text2query.benchmark.progress` (Task 1).
- Produces: `load_tpch_data(data_dir, db_url, on_item_start=print_item_start, on_item_done=print_item_done) -> dict[str, int]` — unchanged return type and default console output.

- [ ] **Step 1: Write the failing test**

Create `app/tests/test_data_loader.py`:

```python
from unittest.mock import MagicMock, patch

from text2query.benchmark.data_loader import TPCH_TABLES, load_tpch_data


def test_load_tpch_data_invokes_item_callbacks(tmp_path):
    for table in TPCH_TABLES:
        (tmp_path / f"{table}.tbl").write_text("1|2|3|\n")

    fake_cursor = MagicMock()
    fake_cursor.rowcount = 1
    fake_conn = MagicMock()
    fake_conn.connection.cursor.return_value = fake_cursor
    fake_engine = MagicMock()
    fake_engine.begin.return_value.__enter__.return_value = fake_conn
    fake_engine.begin.return_value.__exit__.return_value = False

    starts = []
    outcomes = []

    with patch(
        "text2query.database.schema.create_engine_for_database", return_value=fake_engine
    ), patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.wait.return_value = None
        mock_popen.return_value.returncode = 0
        mock_popen.return_value.stdout = None

        loaded = load_tpch_data(
            tmp_path, "postgresql://fake",
            on_item_start=lambda i, total, label: starts.append((i, total, label)),
            on_item_done=lambda outcome: outcomes.append(outcome),
        )

    assert loaded == {t: 1 for t in TPCH_TABLES}
    assert [s[:2] for s in starts] == [(i, len(TPCH_TABLES)) for i in range(1, len(TPCH_TABLES) + 1)]
    assert outcomes == [" ✓ 1 rows"] * len(TPCH_TABLES)
```

Note: `load_tpch_data` imports `create_engine_for_database` *inside the function body* (`from text2query.database.schema import create_engine_for_database`), so the patch target is `text2query.database.schema.create_engine_for_database`, not a `data_loader`-qualified name.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_data_loader.py -v`
Expected: FAIL with `TypeError: load_tpch_data() got an unexpected keyword argument 'on_item_start'`

- [ ] **Step 3: Update `load_tpch_data` in `data_loader.py`**

Add to the top imports of `app/src/text2query/benchmark/data_loader.py`:

```python
from text2query.benchmark.progress import print_item_done, print_item_start
```

Replace the `load_tpch_data` function with:

```python
def load_tpch_data(
    data_dir: Path,
    db_url: str,
    on_item_start=print_item_start,
    on_item_done=print_item_done,
) -> dict[str, int]:
    """Load .tbl files into PostgreSQL using COPY.

    Returns dict mapping table names to row counts.
    """
    from text2query.database.schema import create_engine_for_database

    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    missing = [t for t in TPCH_TABLES if not (data_dir / f"{t}.tbl").exists()]
    if missing:
        raise FileNotFoundError(f"Missing .tbl files: {', '.join(missing)}")

    engine = create_engine_for_database(db_url)
    loaded = {}

    for i, table in enumerate(TPCH_TABLES, 1):
        tbl_file = data_dir / f"{table}.tbl"
        size = _fmt_size(os.path.getsize(tbl_file))
        on_item_start(i, len(TPCH_TABLES), f"{table} ({size})")

        with engine.begin() as conn:
            raw = conn.connection
            cur = raw.cursor()
            try:
                proc = subprocess.Popen(
                    ["sed", "s/|$//", str(tbl_file)],
                    stdout=subprocess.PIPE,
                )
                cur.copy_expert(
                    f"COPY {table} FROM STDIN WITH (FORMAT csv, DELIMITER '|', NULL '')",
                    proc.stdout,
                )
                proc.wait()
                if proc.returncode != 0:
                    raise RuntimeError(f"sed failed with exit code {proc.returncode}")
            except Exception as e:
                cur.close()
                raise RuntimeError(f"COPY failed for {table}: {e}")

            loaded[table] = cur.rowcount
            cur.close()

        on_item_done(f" ✓ {loaded[table]:,} rows")

    return loaded
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_data_loader.py -v`
Expected: 1 passed

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add app/src/text2query/benchmark/data_loader.py app/tests/test_data_loader.py
git commit -m "refactor: make load_tpch_data progress narration injectable"
```

---

### Task 5: Callback-driven progress in `_run_single_generation`

**Files:**
- Modify: `app/src/text2query/benchmark/runner.py` (top imports + `_run_single_generation`, lines 30–119)
- Modify: `app/tests/test_multi_seed.py` (add import + one test)

**Interfaces:**
- Consumes: `print_item_start`, `print_item_done` from `text2query.benchmark.progress` (Task 1).
- Produces: `_run_single_generation(..., on_item_start=print_item_start, on_item_done=print_item_done) -> None` — unchanged return type and default console output. `run_llm_generation`'s signature and behavior are unaffected (it still calls `_run_single_generation` with defaults).

- [ ] **Step 1: Write the failing test**

In `app/tests/test_multi_seed.py`, update the import line:

```python
from text2query.benchmark.runner import run_llm_generation
```

to:

```python
from text2query.benchmark.runner import _run_single_generation, run_llm_generation
```

Then add this test function (near the other generation tests, after `test_run_llm_generation_caching_per_seed`):

```python
def test_run_single_generation_invokes_item_callbacks(tmp_path):
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    starts = []
    outcomes = []

    with patch(
        "text2query.llm.ollama.generate_sql",
        return_value=GenerationResult(sql="SELECT name FROM customers;"),
    ), patch("text2query.benchmark.runner.create_engine_for_database"), \
       patch("text2query.llm.ollama.warmup", return_value=True), \
       patch("text2query.benchmark.runner.get_database_schema_string", return_value="schema"):

        _run_single_generation(
            questions_dir, output_dir, "db://url", "test-model",
            on_item_start=lambda i, total, label: starts.append((i, total, label)),
            on_item_done=lambda outcome: outcomes.append(outcome),
        )

    assert starts == [(1, 1, "Q01")]
    assert outcomes == [" ✓"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_multi_seed.py -v`
Expected: FAIL with `TypeError: _run_single_generation() got an unexpected keyword argument 'on_item_start'`

- [ ] **Step 3: Update `_run_single_generation` in `runner.py`**

Add to the top imports of `app/src/text2query/benchmark/runner.py`:

```python
from text2query.benchmark.progress import print_item_done, print_item_start
```

Replace the `_run_single_generation` function (lines 30–119) with:

```python
def _run_single_generation(
    questions_dir: Path,
    output_dir: Path,
    db_url: str,
    model: str,
    seed: int | None = None,
    query_ids: list[str] | None = None,
    on_item_start=print_item_start,
    on_item_done=print_item_done,
) -> None:
    question_files = sorted(questions_dir.glob("*.md"))
    if query_ids is not None:
        question_files = [q for q in question_files if q.stem in query_ids]
    total = len(question_files)

    output_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine_for_database(db_url)
    schema = get_database_schema_string(engine)

    fingerprint = GenerationFingerprint(
        model=model,
        prompt_template=get_prompt_template(),
        schema=schema,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        seed=seed,
    )

    cached_fingerprint = read_manifest_fingerprint(output_dir)
    if cached_fingerprint is not None and cached_fingerprint != fingerprint.hash:
        print(f"  ⚠ Generation config changed since last run — clearing stale cache in {output_dir}")
        _clear(output_dir, ("*.sql", "*.prompt", "*.raw"))
    write_manifest(output_dir, fingerprint.hash, asdict(fingerprint))

    # Cache: skip queries whose .sql file already exists. Safe to resume from — the
    # fingerprint check above guarantees the cache reflects the current model, prompt,
    # schema, temperature, and seed; a mismatch clears it before we get here.
    existing = {f.stem for f in output_dir.glob("*.sql")}
    to_process = [q for q in question_files if q.stem not in existing]

    if not to_process:
        print(f"  ✓ All {total} queries already generated in {output_dir}")
        return

    seed_label = f" (seed={seed})" if seed is not None else ""
    cache_label = f", {len(existing)} cached" if existing else ""
    print(f"  Generating {len(to_process)} queries{seed_label}{cache_label}...")

    print(f"  Warming up {model}...", end="", flush=True)
    print(" ✓" if ollama.warmup(model) else " ⚠ (warmup failed, continuing)")

    success = 0
    errors = []
    process_total = len(to_process)

    for i, qfile in enumerate(to_process, 1):
        query_id = qfile.stem
        question = read_business_question(qfile)
        if not question:
            on_item_start(i, process_total, f"Q{query_id}")
            on_item_done(" ⚠ no question found, skipping")
            continue

        on_item_start(i, process_total, f"Q{query_id}")

        result = ollama.generate_sql(question, schema, model, seed=seed)
        generated_sql = result.sql
        raw_response = result.raw_response
        prompt = result.prompt
        error = result.error

        if prompt is not None:
            (output_dir / f"{query_id}.prompt").write_text(prompt)

        if generated_sql:
            output_file = output_dir / f"{query_id}.sql"
            output_file.write_text(generated_sql)
            on_item_done(" ✓")
            success += 1
        else:
            raw_file = output_dir / f"{query_id}.raw"
            if error:
                raw_file.write_text(f"ERROR: {error}\n")
            elif raw_response:
                raw_file.write_text(raw_response)
            on_item_done(" ✗")
            errors.append((query_id, error or "No SQL extracted"))

    print(f"  ✓ Generated {success} queries -> {output_dir}")
    if errors:
        print(f"  ⚠ {len(errors)} failed:")
        for query_id, error in errors:
            print(f"    - Q{query_id}: {error[:60]}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multi_seed.py -v`
Expected: all tests in the file pass (existing ones + the new one)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add app/src/text2query/benchmark/runner.py app/tests/test_multi_seed.py
git commit -m "refactor: make _run_single_generation progress narration injectable"
```

---

### Task 6: Extract `_resolve_query_id_filter` from `main()`

**Files:**
- Modify: `app/src/text2query/benchmark/benchmarking.py`
- Test: `app/tests/test_benchmarking.py`

**Interfaces:**
- Produces: `_resolve_query_id_filter(requested: list[str] | None, available: list[str]) -> tuple[list[str] | None, list[str]]` in `benchmarking.py`.

- [ ] **Step 1: Write the failing test**

Create `app/tests/test_benchmarking.py`:

```python
from text2query.benchmark.benchmarking import _resolve_query_id_filter


def test_no_filter_requested_returns_none():
    resolved, skipped = _resolve_query_id_filter(None, ["01", "02"])
    assert resolved is None
    assert skipped == []


def test_filter_keeps_only_available_ids():
    resolved, skipped = _resolve_query_id_filter(["01", "99"], ["01", "02"])
    assert resolved == ["01"]
    assert skipped == ["99"]


def test_filter_with_no_matches_returns_empty_list():
    resolved, skipped = _resolve_query_id_filter(["99"], ["01", "02"])
    assert resolved == []
    assert skipped == ["99"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_benchmarking.py -v`
Expected: FAIL with `ImportError: cannot import name '_resolve_query_id_filter'`

- [ ] **Step 3: Add the function and use it in `main()`**

In `app/src/text2query/benchmark/benchmarking.py`, add this function above `main()` (after `_run_single_model_benchmark`):

```python
def _resolve_query_id_filter(
    requested: list[str] | None, available: list[str],
) -> tuple[list[str] | None, list[str]]:
    """Validate a BENCHMARK_QUERY_IDS-style filter against available query IDs.

    Returns (resolved_ids, skipped_ids). resolved_ids is None when no filter
    is requested, or an empty list when a filter is requested but nothing in
    it matches `available`.
    """
    if requested is None:
        return None, []
    valid = [q for q in requested if q in available]
    skipped = [q for q in requested if q not in available]
    return valid, skipped
```

Then, inside `main()`, replace:

```python
        query_ids: list[str] | None = None
        if BENCHMARK_QUERY_IDS is not None:
            available = sorted(f.stem for f in queries_dir.glob("*.sql"))
            valid = [q for q in BENCHMARK_QUERY_IDS if q in available]
            skipped = [q for q in BENCHMARK_QUERY_IDS if q not in available]
            if skipped:
                print(f"  ⚠ Unknown query IDs (skipped): {', '.join(skipped)}")
            if not valid:
                print("  ✗ No valid query IDs remain after filtering — aborting")
                sys.exit(1)
            query_ids = valid
            print(f"  Query filter active: {len(query_ids)} / {len(available)} queries selected ({', '.join(query_ids)})")
            print()
```

with:

```python
        available = sorted(f.stem for f in queries_dir.glob("*.sql"))
        query_ids, skipped = _resolve_query_id_filter(BENCHMARK_QUERY_IDS, available)
        if skipped:
            print(f"  ⚠ Unknown query IDs (skipped): {', '.join(skipped)}")
        if query_ids is not None and not query_ids:
            print("  ✗ No valid query IDs remain after filtering — aborting")
            sys.exit(1)
        if query_ids:
            print(f"  Query filter active: {len(query_ids)} / {len(available)} queries selected ({', '.join(query_ids)})")
            print()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_benchmarking.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add app/src/text2query/benchmark/benchmarking.py app/tests/test_benchmarking.py
git commit -m "refactor: extract _resolve_query_id_filter from main()"
```

---

### Task 7: Group output paths into `BenchmarkPaths`

**Files:**
- Modify: `app/src/text2query/benchmark/benchmarking.py`
- Modify: `app/tests/test_benchmarking.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `BenchmarkPaths` (frozen dataclass with 8 `Path` fields + `BenchmarkPaths.defaults()` classmethod) in `benchmarking.py`. `_run_single_model_benchmark(model, paths, db_url, seeds, query_ids=None)` — signature changes from 9 individual path parameters to one `paths: BenchmarkPaths`.

- [ ] **Step 1: Write the failing tests**

Append to `app/tests/test_benchmarking.py`:

```python
from pathlib import Path
from unittest.mock import patch

from text2query.benchmark.benchmarking import BenchmarkPaths, _run_single_model_benchmark


def test_benchmark_paths_defaults():
    paths = BenchmarkPaths.defaults()
    assert paths.schema_file == Path("benchmark/.tpch/schema.sql")
    assert paths.output_dir == Path("benchmark/queries")
    assert paths.results_base == Path("benchmark/results")


def test_run_single_model_benchmark_builds_per_model_subdirs():
    paths = BenchmarkPaths(
        schema_file=Path("s"), questions_dir=Path("q"), queries_dir=Path("qq"),
        answers_dir=Path("a"), output_dir=Path("out"), generated_answers_dir=Path("ga"),
        report_dir=Path("rep"), results_base=Path("res"),
    )
    captured = {}

    def fake_run_llm_generation(*, questions_dir, output_dir, db_url, model, seeds, query_ids):
        captured["run_llm_generation_output_dir"] = output_dir

    def fake_execute_generated_queries(*, queries_dir, answers_dir, db_url, seeds, query_ids):
        captured["execute_answers_dir"] = answers_dir

    def fake_generate_reports(**kwargs):
        captured["report_dir"] = kwargs["report_dir"]
        return [{"query_id": 1}]

    with patch("text2query.benchmark.benchmarking.run_llm_generation", fake_run_llm_generation), \
         patch("text2query.benchmark.benchmarking.execute_generated_queries", fake_execute_generated_queries), \
         patch("text2query.benchmark.benchmarking.generate_reports", fake_generate_reports):

        results = _run_single_model_benchmark(
            model="qwen2.5-coder:7b", paths=paths, db_url="db://url", seeds=[1],
        )

    assert captured["run_llm_generation_output_dir"] == Path("out/qwen2.5-coder_7b")
    assert captured["execute_answers_dir"] == Path("ga/qwen2.5-coder_7b")
    assert captured["report_dir"] == Path("rep/qwen2.5-coder_7b")
    assert results == [{"query_id": 1}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_benchmarking.py -v`
Expected: FAIL with `ImportError: cannot import name 'BenchmarkPaths'`

- [ ] **Step 3: Add `BenchmarkPaths` and update `_run_single_model_benchmark`**

In `app/src/text2query/benchmark/benchmarking.py`, add to the top imports:

```python
from dataclasses import dataclass
```

Add this class above `_run_single_model_benchmark`:

```python
@dataclass(frozen=True)
class BenchmarkPaths:
    """Filesystem layout for a benchmark run."""
    schema_file: Path
    questions_dir: Path
    queries_dir: Path
    answers_dir: Path
    output_dir: Path
    generated_answers_dir: Path
    report_dir: Path
    results_base: Path

    @classmethod
    def defaults(cls) -> "BenchmarkPaths":
        return cls(
            schema_file=Path("benchmark/.tpch/schema.sql"),
            questions_dir=Path("benchmark/.tpch/questions"),
            queries_dir=Path("benchmark/.tpch/queries"),
            answers_dir=Path("benchmark/.tpch/answers"),
            output_dir=Path("benchmark/queries"),
            generated_answers_dir=Path("benchmark/answers"),
            report_dir=Path("benchmark/reports"),
            results_base=Path("benchmark/results"),
        )
```

Replace `_run_single_model_benchmark`'s signature and body:

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

- [ ] **Step 4: Update `main()` to build and use `paths`**

Replace the path-construction block:

```python
    schema_file = Path("benchmark/.tpch/schema.sql")
    questions_dir = Path("benchmark/.tpch/questions")
    queries_dir = Path("benchmark/.tpch/queries")
    answers_dir = Path("benchmark/.tpch/answers")
    output_dir = Path("benchmark/queries")
    generated_answers_dir = Path("benchmark/answers")
    report_dir = Path("benchmark/reports")
    results_base = Path("benchmark/results")
    data_dir = Path(BENCHMARK_DATA_PATH) if BENCHMARK_DATA_PATH else Path(f"benchmark/.tpch/data/sf{BENCHMARK_SCALE_FACTOR}")
```

with:

```python
    paths = BenchmarkPaths.defaults()
    data_dir = Path(BENCHMARK_DATA_PATH) if BENCHMARK_DATA_PATH else Path(f"benchmark/.tpch/data/sf{BENCHMARK_SCALE_FACTOR}")
```

Then update every remaining reference in `main()`, in order of appearance:

- `available = sorted(f.stem for f in queries_dir.glob("*.sql"))` → `available = sorted(f.stem for f in paths.queries_dir.glob("*.sql"))`
- `validate_directories(questions_dir, queries_dir)` → `validate_directories(paths.questions_dir, paths.queries_dir)`
- `setup_database(schema_file=schema_file, data_dir=data_dir, db_url=DATABASE_URL)` → `setup_database(schema_file=paths.schema_file, data_dir=data_dir, db_url=DATABASE_URL)`
- `generate_answers(queries_dir=queries_dir, answers_dir=answers_dir, db_url=DATABASE_URL)` → `generate_answers(queries_dir=paths.queries_dir, answers_dir=paths.answers_dir, db_url=DATABASE_URL)`
- The `_run_single_model_benchmark(...)` call:

```python
            results = _run_single_model_benchmark(
                model=model,
                questions_dir=questions_dir,
                queries_dir=queries_dir,
                answers_dir=answers_dir,
                output_base=output_dir,
                generated_answers_base=generated_answers_dir,
                report_base=report_dir,
                db_url=DATABASE_URL,
                seeds=seeds,
                query_ids=query_ids,
            )
```

  becomes:

```python
            results = _run_single_model_benchmark(
                model=model,
                paths=paths,
                db_url=DATABASE_URL,
                seeds=seeds,
                query_ids=query_ids,
            )
```

- `generate_cross_model_report(models=models, reference_queries_dir=queries_dir, report_dir=report_dir, precomputed=precomputed, seeds=seeds, selected_ids=query_ids)` → use `reference_queries_dir=paths.queries_dir, report_dir=paths.report_dir`
- `fingerprints = collect_fingerprints(output_dir)` → `collect_fingerprints(paths.output_dir)`
- `session_dir = archive_session(queries_dir=output_dir, answers_dir=generated_answers_dir, report_dir=report_dir, results_base=results_base)` → `archive_session(queries_dir=paths.output_dir, answers_dir=paths.generated_answers_dir, report_dir=paths.report_dir, results_base=paths.results_base)`
- `total_questions = len(list(questions_dir.glob("*.md")))` → `paths.questions_dir`
- `total_gt = len(list(queries_dir.glob("*.sql")))` → `paths.queries_dir`

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_benchmarking.py -v`
Expected: 5 passed

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add app/src/text2query/benchmark/benchmarking.py app/tests/test_benchmarking.py
git commit -m "refactor: group benchmark output paths into BenchmarkPaths"
```

---

### Task 8: Extract `format_run_summary`

**Files:**
- Modify: `app/src/text2query/benchmark/reporting.py`
- Modify: `app/src/text2query/benchmark/benchmarking.py`
- Modify: `app/tests/test_reporting.py`

**Interfaces:**
- Produces: `format_run_summary(*, total_questions, total_ground_truth, query_ids, models, num_seeds, session_dir, database_url) -> str` in `reporting.py`.

- [ ] **Step 1: Write the failing tests**

Append to `app/tests/test_reporting.py`:

```python
from pathlib import Path

from text2query.benchmark.reporting import format_run_summary


def test_format_run_summary_single_model_all_queries():
    summary = format_run_summary(
        total_questions=22, total_ground_truth=22, query_ids=None,
        models=["m1"], num_seeds=1, session_dir=Path("benchmark/results/x"),
        database_url="postgresql://u:p@host/db",
    )
    assert "Queries benchmarked: 22 / 22 (all)" in summary
    assert "Model:               m1" in summary
    assert "Total evaluations:   22 (22 queries × 1 seeds × 1 model)" in summary


def test_format_run_summary_multi_model_filtered_queries():
    summary = format_run_summary(
        total_questions=22, total_ground_truth=22, query_ids=["01", "02"],
        models=["m1", "m2"], num_seeds=3, session_dir=Path("benchmark/results/x"),
        database_url="postgresql://u:p@host/db",
    )
    assert "Queries benchmarked: 2 / 22 (01, 02)" in summary
    assert "Models:              m1, m2" in summary
    assert "Total evaluations:   12 (2 queries × 3 seeds × 2 models)" in summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_reporting.py -v`
Expected: FAIL with `ImportError: cannot import name 'format_run_summary'`

- [ ] **Step 3: Add `format_run_summary` to `reporting.py`**

Append to the end of `app/src/text2query/benchmark/reporting.py`:

```python
def format_run_summary(
    *,
    total_questions: int,
    total_ground_truth: int,
    query_ids: list[str] | None,
    models: list[str],
    num_seeds: int,
    session_dir: Path,
    database_url: str,
) -> str:
    """Render the closing 'Benchmark Complete' summary block."""
    lines = ["=" * 60, "  Benchmark Complete", "=" * 60, "", "Summary:"]

    if query_ids is not None:
        lines.append(f"  - Queries benchmarked: {len(query_ids)} / {total_questions} ({', '.join(query_ids)})")
    else:
        lines.append(f"  - Queries benchmarked: {total_questions} / {total_questions} (all)")

    lines.append(f"  - Ground truth:        {total_ground_truth} queries available")

    if len(models) > 1:
        lines.append(f"  - Models:              {', '.join(models)}")
    else:
        lines.append(f"  - Model:               {models[0]}")

    lines.append(f"  - Seeds per query:     {num_seeds}")

    benchmarked_count = len(query_ids) if query_ids else total_questions
    total_evals = benchmarked_count * num_seeds
    lines.append(
        f"  - Total evaluations:   {total_evals} "
        f"({benchmarked_count} queries × {num_seeds} seeds × {len(models)} model{'s' if len(models) > 1 else ''})"
    )
    lines.append(f"  - Session:             {session_dir}")
    lines.append(f"  - Database:            {database_url}")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Wire it into `main()`**

In `app/src/text2query/benchmark/benchmarking.py`, add `format_run_summary` to the existing `reporting` import block:

```python
from text2query.benchmark.reporting import (
    generate_reports,
    generate_cross_model_report,
    archive_session,
    write_session_manifest,
    format_run_summary,
)
```

Replace the closing summary block in `main()`:

```python
        print("=" * 60)
        print("  Benchmark Complete")
        print("=" * 60)
        print()

        total_questions = len(list(paths.questions_dir.glob("*.md")))
        total_gt = len(list(paths.queries_dir.glob("*.sql")))

        print("Summary:")
        if query_ids is not None:
            print(f"  - Queries benchmarked: {len(query_ids)} / {total_questions} ({', '.join(query_ids)})")
        else:
            print(f"  - Queries benchmarked: {total_questions} / {total_questions} (all)")
        print(f"  - Ground truth:        {total_gt} queries available")
        if multi_model:
            print(f"  - Models:              {', '.join(models)}")
        else:
            print(f"  - Model:               {models[0]}")
        print(f"  - Seeds per query:     {BENCHMARK_NUM_SEEDS}")
        benchmarked_count = len(query_ids) if query_ids else total_questions
        total_evals = benchmarked_count * BENCHMARK_NUM_SEEDS
        print(f"  - Total evaluations:   {total_evals} ({benchmarked_count} queries × {BENCHMARK_NUM_SEEDS} seeds × {len(models)} model{'s' if len(models) > 1 else ''})")
        print(f"  - Session:             {session_dir}")
        print(f"  - Database:            {DATABASE_URL}")
        print()

        return 0
```

with:

```python
        print(format_run_summary(
            total_questions=len(list(paths.questions_dir.glob("*.md"))),
            total_ground_truth=len(list(paths.queries_dir.glob("*.sql"))),
            query_ids=query_ids,
            models=models,
            num_seeds=BENCHMARK_NUM_SEEDS,
            session_dir=session_dir,
            database_url=DATABASE_URL,
        ))

        return 0
```

(`multi_model` is still used earlier in `main()` for the "Multi-Model Benchmark" banner — leave that usage as-is.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reporting.py -v`
Expected: all tests in the file pass (existing + 2 new)

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add app/src/text2query/benchmark/reporting.py app/src/text2query/benchmark/benchmarking.py app/tests/test_reporting.py
git commit -m "refactor: extract format_run_summary from main()"
```

---

### Task 9: Module docstrings, README methodology section, final verification

**Files:**
- Modify: `app/src/text2query/benchmark/benchmarking.py`, `data_loader.py`, `fingerprint.py`, `pipeline.py`, `reporting.py`, `runner.py`, `similarity.py` (one-line module docstring each; `progress.py` already has one from Task 1)
- Modify: `README.md`

This task has no new logic, so it has no failing-test step — it ends with the full-suite verification instead.

- [ ] **Step 1: Add a one-line module docstring to each file**

As the very first line of each file (before existing imports), add:

- `app/src/text2query/benchmark/benchmarking.py` — keep the existing `#!/usr/bin/env python3` as line 1, add directly below it:
  ```python
  """Benchmark CLI entry point: orchestrates the full evaluation pipeline end to end."""
  ```
- `app/src/text2query/benchmark/data_loader.py`:
  ```python
  """Stage: generate and load TPC-H data into the database."""
  ```
- `app/src/text2query/benchmark/fingerprint.py`:
  ```python
  """Cache-invalidation fingerprints for generation/execution artifacts."""
  ```
- `app/src/text2query/benchmark/pipeline.py`:
  ```python
  """Stages: data generation, validation, database setup, and query execution."""
  ```
- `app/src/text2query/benchmark/reporting.py`:
  ```python
  """Stage: score aggregation, report rendering, and session archiving."""
  ```
- `app/src/text2query/benchmark/runner.py`:
  ```python
  """Stage: LLM SQL generation and generated-query execution, per seed."""
  ```
- `app/src/text2query/benchmark/similarity.py`:
  ```python
  """Scoring: result-set and AST similarity metrics between generated and reference SQL."""
  ```

- [ ] **Step 2: Expand the README's Benchmark Mode section**

In `README.md`, replace:

```markdown
## Benchmark Mode

```bash
docker compose exec ollama pull-models benchmark
docker compose --profile benchmark up --build benchmark
```

Runs the TPC-H pipeline and scores generated SQL (Result F1, AST similarity) across the models/seeds/queries set via `BENCHMARK_MODELS`, `BENCHMARK_NUM_SEEDS`, and `BENCHMARK_QUERY_IDS` above. Results archive to `benchmark/results/<timestamp>/` with a manifest describing the run.
```

with:

```markdown
## Benchmark Mode

```bash
docker compose exec ollama pull-models benchmark
docker compose --profile benchmark up --build benchmark
```

Runs a six-stage evaluation pipeline against TPC-H, scoring generated SQL (Result F1, AST similarity) across the models/seeds/queries set via `BENCHMARK_MODELS`, `BENCHMARK_NUM_SEEDS`, and `BENCHMARK_QUERY_IDS` above:

1. **Data Generation** — generate (or reuse cached) TPC-H data at the configured scale factor.
2. **Validation** — confirm the expected question/query files are present.
3. **Database Setup** — load the schema, data, and indexes if the database isn't already populated.
4. **Answer Generation** — execute the reference SQL to produce ground-truth answers.
5. **Per-model Generation, Execution & Scoring** — for each model in `BENCHMARK_MODELS`: generate SQL via the LLM, execute it, and score it against the ground truth.
6. **Cross-Model Comparison & Archiving** — when multiple models are configured, compare them side by side; archive the run to `benchmark/results/<timestamp>/` with a manifest describing the run.
```

- [ ] **Step 3: Run the full test suite**

Run (from `app/`): `.venv/bin/python -m pytest -v`
Expected: all tests pass (88 original + 1 progress + 6 setup_database + 1 pipeline_helpers + 1 data_loader + 1 multi_seed + 3 benchmarking (Task 6) + 2 benchmarking (Task 7) + 2 reporting = 105 tests)

- [ ] **Step 4: Manual smoke check (not automated — flag for the user)**

This plan's automated tests mock every LLM/DB call, so they can't catch a console-output regression end to end. Before considering this refactor done, run the real pipeline once and confirm the console output looks the same as before the refactor:

```bash
docker compose exec ollama pull-models benchmark
docker compose --profile benchmark up --build benchmark
```

This step requires Docker and a running Ollama instance and cannot be executed inside this planning/implementation session — call it out to the user as a manual follow-up.

- [ ] **Step 5: Commit**

```bash
git add app/src/text2query/benchmark/benchmarking.py app/src/text2query/benchmark/data_loader.py app/src/text2query/benchmark/fingerprint.py app/src/text2query/benchmark/pipeline.py app/src/text2query/benchmark/reporting.py app/src/text2query/benchmark/runner.py app/src/text2query/benchmark/similarity.py README.md
git commit -m "docs: add benchmark module docstrings and expand README methodology section"
```
