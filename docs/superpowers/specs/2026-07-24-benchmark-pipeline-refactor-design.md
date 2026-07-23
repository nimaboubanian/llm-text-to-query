# Benchmark Pipeline Refactor — Design

## Goal

`benchmark/` is the research core of this project — it evaluates local LLMs on TPC-H text-to-SQL accuracy, and `server`/`llm`/`database` exist to support that evaluation. The goal of this refactor is to make `benchmark/`'s structure and documentation read like a deliberately designed evaluation pipeline (the kind you'd present in an academic writeup), rather than a script that grew commit by commit — without a rewrite, and without changing any externally visible interface.

## Evidence (from the code graph + source read)

- `list_graph_stats_tool` / `get_architecture_overview_tool`: 7 directory-based communities, near-zero cross-community coupling (4 community pairs, max 8 edges), no coupling warnings. The module boundaries (`server`, `llm`, `database`, `benchmark`, `tests`) are already sound.
- `get_hub_nodes_tool`: `benchmarking.py::main` (95 total degree), `reporting.py::generate_reports` (43), `runner.py::_run_single_generation` (41), `similarity.py::_result_set_comparison` (35), `pipeline.py::setup_database` (33) dominate the call graph.
- `get_knowledge_gaps_tool`: 20 "untested hotspots," all in `benchmark/`, exactly the same functions flagged as hubs above.
- Reading the source confirmed *why*: these functions interleave business logic with `print()`-based progress narration (indentation, ✓/✗/⚠ ticks, section banners) at nearly every step. That inflates their call-graph fan-out and makes them awkward to unit-test in isolation — which is exactly why they're untested.
- By contrast, `server/main.py` and `llm/service.py` were read in full and are already clean: small functions, `logging` module (not `print`), docstrings that explain non-obvious *why* (SQL-injection guard, Postgres-type JSON coercion). **No changes are needed outside `benchmark/`.**
- The pipeline's actual stages are already implicit and sound: Data Generation → Validation → DB Setup → Answer Generation → per-model (Generation → Execution → Scoring) → Cross-Model Comparison → Archiving. The refactor makes this explicit; it does not invent a new structure.

## Non-goals

- No changes to `server/`, `llm/`, or `database/` — confirmed clean by direct source read.
- No new CLI flags, env vars, or Docker Compose changes. External interfaces are free to be *renamed* if genuinely unclear, but nothing found during design warranted it — `BENCHMARK_MODELS`, `BENCHMARK_NUM_SEEDS`, `BENCHMARK_QUERY_IDS`, `BENCHMARK_SCALE_FACTOR`, and the `docker compose --profile benchmark` commands stay as-is.
- No new test framework or mocking library — continue with `pytest` + stdlib `unittest.mock`, matching `app/tests/`'s existing style.
- No formal `Stage`/`Pipeline` class hierarchy. Considered and rejected: ~1400 lines of already-working procedural code across 7 files doesn't warrant an interface/runner abstraction. The fix is separating narration from logic, not introducing OO ceremony.
- Console output format is unchanged. The refactor relocates *where* the print statements live, not *what* they print.

## Design

### 1. Separate narration from logic

**Before/after-style steps** (schema load, data load, index build, directory validation, DB readiness check, archiving): the print statement that currently follows each internal step moves out of the logic function and into its caller. This mostly means finishing decompositions the print statements already implied:

- `pipeline.py::setup_database` (currently: load schema → print, load data → print, build indexes → print, all in one function) splits into `load_schema`, `load_data`, `build_indexes`, each returning a result (row counts, etc.) with no print calls. The caller (`main()`'s "Setup Database" step) prints the same three lines it does today, driven by the returned results.
- Similarly for `validate_directories`, `check_database_readiness`, `generate_data`, `archive_session`, `write_session_manifest`: print calls move to the call site in `main()` / `_run_single_model_benchmark`, driven by return values.

**Per-item progress loops** (`runner.py::_run_single_generation` ticking off each generated query, `pipeline.py::execute_queries_to_csv` ticking off each executed query): these take an optional `on_item` callback, defaulting to the current print-based renderer for CLI use. Tests omit the callback and assert directly on the returned results list — no stdout capture needed.

### 2. Decompose `main()`

`benchmarking.py::main()` (190 lines, 95-node fan-out) is split into named pieces without changing its overall sequence:

- `_resolve_query_id_filter(available, requested) -> list[str] | None` — extracts the existing filter/validation logic (currently inline, lines ~119–131).
- A small dataclass/dict grouping the ~9 hardcoded output paths (`questions_dir`, `queries_dir`, `answers_dir`, `output_dir`, ...), since `_run_single_model_benchmark` already takes 9 path-shaped parameters individually.
- `format_run_summary(...) -> str` in `reporting.py` — extracts the closing 20-line summary block, returning text instead of printing inline.

`main()` itself becomes a short, top-to-bottom sequence of named calls that reads as the methodology: resolve config → resolve paths → filter queries → prepare data → validate → ensure DB → generate answers → per-model loop → cross-model comparison → archive → summarize.

### 3. Testing

Once narration is out of the logic functions, the 20 flagged hotspots become plain input→output functions and get direct unit tests in the existing style (small `test_*` functions, stdlib mocking for the one LLM/DB call each needs stubbed). Specifically: `load_schema`, `load_data`, `build_indexes`, `_resolve_query_id_filter`, `format_run_summary`, and the callback-driven loop bodies (asserted via their returned results, not stdout).

Existing integration-style tests (`test_multi_seed.py`, `test_benchmark_caching.py`) are unaffected — the public function signatures they exercise (`run_llm_generation`, `execute_generated_queries`, etc.) don't change, only their internals stop printing directly.

### 4. Docs

- `README.md`'s "Benchmark Mode" section expands from two commands into a short paragraph naming the six real stages (Data Generation → Validation → DB Setup → Answer Generation → per-model Generation/Execution/Scoring → Cross-Model Comparison → Archiving).
- Each `benchmark/*.py` file gets a one-line module docstring naming its stage. Function-level docstrings are already good where they exist and aren't rewritten wholesale.
- No standalone architecture doc — this design doc is the fuller writeup; README stays the quick reference.

## Risks / edge cases

- Splitting `setup_database` and similar functions changes their return type (from `None` to a result). Anything currently ignoring the return value is unaffected; anything relying on `None` specifically (unlikely — checked, nothing does) would need updating.
- The `on_item` callback default must reproduce today's exact print formatting (ticks, truncated error messages, cache-skip counts) to keep console output byte-for-byte equivalent — this is the main regression risk and should be verified by running the benchmark profile end-to-end and diffing output against a pre-refactor run.
- `generate_reports` / `generate_cross_model_report` were not included in the before/after-style split above — they already return structured results (`list[dict]`) alongside their prints; only the two or three narration `print()` lines inside them need to move to their callers, no deeper restructuring needed there.

## Success criteria

- `docker compose --profile benchmark up --build benchmark` produces console output unchanged from today (modulo intentional formatting fixes, if any surface during implementation).
- The 20 previously-untested hotspot functions (per `get_knowledge_gaps_tool`) have direct unit tests.
- `main()` is reduced from one 190-line function to a short call sequence plus small named helpers.
- README's Benchmark Mode section describes the six pipeline stages.
- All existing tests continue to pass unmodified.
