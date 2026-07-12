# LLM Text-to-Query

Convert natural language to SQL queries using local LLMs. Two modes, each with a single, non-interactive interface:

- **App** — ask a question, get an answer. `docker compose exec app text2query '...'`, or POST the same question from any container on the Docker network.
- **Benchmark** — evaluate SQL-generation quality against the TPC-H benchmark, with heavy, feature-rich reporting.

Everything runs inside Docker. There is no REPL, no in-session settings, and no model-switching at runtime — all configuration lives in `compose.yml`.

## Quick Start

```bash
# Start services
docker compose up -d

# Pull the model (first run only)
docker compose exec ollama pull-models chat

# Ask a question
docker compose exec app text2query 'What are the customers'"'"' names?'
```

The terminal prints the generated SQL, a table of results, and the row count, then exits.

## App Mode

`docker compose exec app text2query '<question>'` is the only supported CLI interaction. It is a thin client: it POSTs the question to an HTTP server that is the app container's main process, prints the JSON response, and exits.

The same server is reachable from any other container on the Docker network (it is not exposed to the host by default):

```bash
curl -X POST http://app:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "How many customers are there?"}'
```

Response shape:

```json
{
  "sql": "SELECT count(*) FROM customers;",
  "columns": ["count"],
  "rows": [[42]],
  "row_count": 1,
  "error": null
}
```

Errors use the body's `error` field with an HTTP status that indicates where the request failed: `400` for bad input, `422` when SQL couldn't be safely generated, `502` when the database rejects the query. Uncomment the `ports:` line under the `app` service in `compose.yml` to expose port 8000 to the host as well.

The database schema is cached at server startup; if you change the schema, restart the `app` container.

## Configuration

All user-configurable settings are at the top of `compose.yml` in the `x-config` block, split into an App-mode section and a Benchmark-mode section:

```yaml
x-config: &config
  # --- App mode ---
  DEFAULT_MODEL: "qwen2.5-coder:7b"     # Model used for SQL generation
  OLLAMA_URL: "http://ollama:11434"     # LLM backend endpoint
  LOG_LEVEL: "WARNING"                  # DEBUG/INFO/WARNING/ERROR
  LLM_TEMPERATURE: "0.1"                # Sampling temperature
  LLM_NUM_CTX: "4096"                   # Context window (tokens)
  LLM_MAX_TOKENS: "2048"                # Max tokens generated per query
  SERVER_PORT: "8000"                   # Internal HTTP port
  PROMPT_TEMPLATE_PATH: "prompts/sql_generation.txt"

  # --- Benchmark mode ---
  BENCHMARK_MODELS: "llama3.2:3b,qwen2.5-coder:7b"
  BENCHMARK_NUM_SEEDS: "1"
  BENCHMARK_QUERY_IDS: "all"
  BENCHMARK_SCALE_FACTOR: "1"
```

After changing models, recreate the Ollama container to pull them:

```bash
docker compose up -d --force-recreate ollama
docker compose logs -f ollama   # watch download progress
```

## SQL-Generation Prompt

The prompt template used to generate SQL is a plain, user-editable file at `prompts/sql_generation.txt` (mounted read-only into both the `app` and `benchmark` containers). It must contain a `{schema}` and a `{query}` placeholder; edit the rest freely to tune generation behavior.

A small loader validates the file at startup — a missing file, an oversized file, or a template missing a required placeholder fails fast with a clear error rather than producing broken prompts at runtime. Substitution is single-pass plain-token replacement, not string formatting, so placeholder-like text inside the schema or a user's question can never be reinterpreted as template syntax.

The real safety boundary for generated SQL stays output-side (see **Safety** below) — prompt validation only guards against operator misconfiguration, not malicious input.

## Mini Database

A simple e-commerce database (customers, products, orders) loads automatically for testing.

**Example queries:** "What are the customers' names?", "Top 3 best-selling products", "Show customers who spent more than $500 total"

Reset with `docker compose --profile benchmark down -v`.

## Safety

Generated SQL is constrained before execution:

- **Single statement only** — multi-statement input (piggyback queries) is rejected.
- **SELECT-only** — the statement must parse as a `SELECT` (including CTEs and set
  operations like `UNION`); any DDL or DML (`INSERT`, `UPDATE`, `DELETE`, `DROP`, ...)
  is rejected before it ever reaches the database.
- **Read-only transaction** — as defense in depth, every query also runs inside a
  Postgres `READ ONLY` transaction, so a write statement is rejected by the database
  itself even if the SELECT-only check were bypassed.
- **Statement timeout** — capped at 30s per query.
- **Row limit** — results are capped at 10,000 rows.
- **Request boundary** — the App server rejects empty or oversized (>2000 char) questions and non-JSON bodies before they reach the LLM.

## External Database

Edit `DATABASE_URL` in the `app` service in `compose.yml` and remove the `postgres` dependency:

```yaml
environment:
  <<: *config
  DATABASE_URL: postgresql://user:pass@192.168.1.10:5432/mydb
```

For databases on the Docker host, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the `app` service.

## Benchmark Mode

Edit `BENCHMARK_MODELS` in the `x-config` block of `compose.yml` to choose which models to compare (comma-separated). Then pull them and run:

```bash
docker compose exec ollama pull-models benchmark
docker compose --profile benchmark up --build benchmark
```

If you haven't changed `BENCHMARK_MODELS`, the benchmark runs with the default model — just make sure you've already run `pull-models chat`.

Runs a three-phase TPC-H pipeline: **Setup** (data generation, schema loading) → **Generation** (LLM query generation and execution) → **Analysis** (similarity metrics, reports, archiving). The repo-root `benchmark/` directory holds TPC-H data, generated queries/answers, reports, and archived session results — kept under that name for compatibility with existing caches.

Each archived session under `benchmark/results/<timestamp>/` includes a `session_manifest.json`
recording the models, seeds, query filter, scale factor, generation parameters,
the fingerprint(s) that gate the resume cache, the package version, and the database URL
(credentials stripped) — so every archived result is self-describing without cross-referencing
logs or git history.

### Evaluation Metrics

| Metric | Purpose |
|---|---|
| **Result F1** | Primary correctness — did the query produce the right data? |
| **AST Similarity** | Structural closeness of SQL to reference |

### Multi-Seed Mode

Set `BENCHMARK_NUM_SEEDS` in `x-config` to run each query multiple times with different random seeds for statistical robustness (mean, std, 95% CI).

### Query Selection

By default all 22 TPC-H queries are benchmarked. Set `BENCHMARK_QUERY_IDS` to a comma-separated list of query numbers to run only a subset:

```yaml
BENCHMARK_QUERY_IDS: "1,3,7,22"   # run queries 01, 03, 07, 22 only
BENCHMARK_QUERY_IDS: "all"         # run all 22 queries (default)
```

Unknown IDs are warned and skipped; if no valid IDs remain the pipeline aborts. Ground-truth answer generation always runs for all queries regardless of this setting.

### Multi-Model Mode

Set `BENCHMARK_MODELS` in `x-config` to compare models side-by-side. Output includes per-model reports plus `comparison.md` and `results.csv`.

## GPU Acceleration

Pass a compose override — all settings from `compose.yml` are preserved.

**NVIDIA** ([Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) required):

```bash
docker compose -f compose.yml -f compose.nvidia.yml up -d
```

**AMD** ([ROCm drivers](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/) required):

```bash
docker compose -f compose.yml -f compose.amd.yml up -d
```

## Development

```bash
cd app && uv sync --extra dev
uv run pytest -v
```

### Project Structure

```
app/src/text2query/
  core/config.py          # Centralized configuration (env vars)
  core/flags.py            # Feature-flag placeholders (retry/CoT/self-correction)
  llm/provider.py          # LLMProvider interface + factory
  llm/ollama.py            # Ollama implementation of LLMProvider (blocking calls)
  llm/service.py           # Prompt building + SQL extraction/safety (provider-independent)
  llm/prompt_loader.py      # SQL-generation prompt loading + validated substitution
  database/executor.py      # SQL execution -> DataFrame
  database/schema.py        # Schema introspection
  server/main.py            # App-mode HTTP server (POST /query, GET /health)
  server/cli.py             # text2query thin CLI client
  benchmark/                # TPC-H benchmark pipeline + reporting

prompts/sql_generation.txt  # User-editable SQL-generation prompt template
```
