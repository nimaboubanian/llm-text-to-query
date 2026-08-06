# LLM Text-to-Query

Natural language → SQL using local LLMs, via Docker. All config lives in `compose.yml`.

## Quick Start

```bash
docker compose up -d
docker compose exec ollama pull-models chat
docker compose exec app text2query 'What are the customers'"'"' names?'
```

Prints the generated SQL, a result table, and the row count.

## App Mode

```bash
docker compose exec app text2query '<question>'
```

Or POST from any container on the Docker network:

```bash
curl -X POST http://app:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "How many customers are there?"}'
```

Returns `{"sql", "columns", "rows", "row_count", "error"}`. Error statuses: `400` bad input, `422` unsafe/ungenerated SQL, `502` database rejected the query.

Uncomment `ports:` under the `app` service to expose port 8000 to the host. Restart `app` after changing the database schema.

## Configuration

Edit the `x-config` block in `compose.yml`:

```yaml
x-config: &config
  # Shared
  OLLAMA_URL: "http://ollama:11434"
  LOG_LEVEL: "WARNING"
  LLM_TEMPERATURE: "0.1"
  LLM_NUM_CTX: "4096"
  LLM_MAX_TOKENS: "2048"
  # Interactive App mode
  INTERACTIVE_APP_MODEL: "qwen2.5-coder:7b"
  SERVER_PORT: "8000"
  # Benchmark mode
  BENCHMARK_MODELS: "llama3.2:3b,qwen2.5-coder:7b"
  BENCHMARK_NUM_SEEDS: "1"
  BENCHMARK_QUERY_IDS: "all"
  BENCHMARK_SCALE_FACTOR: "1"
```

After changing models:

```bash
docker compose up -d --force-recreate ollama
docker compose logs -f ollama
```

### Prompt features

All default off — the all-off state is the experimental baseline. Enable any
combination in `compose.yml`'s `x-config` block to benchmark their effect:

- `PROMPT_SCHEMA_DDL` — render the schema as `CREATE TABLE` DDL instead of prose
- `PROMPT_SCHEMA_FK` — explicit foreign-key annotations in the schema
- `PROMPT_SCHEMA_DESCRIPTIONS` — curated natural-language column descriptions
- `PROMPT_SCHEMA_SAMPLES` — inline sample values for categorical columns
- `PROMPT_XML_STRUCTURE` — wrap prompt sections in XML tags
- `PROMPT_FEW_SHOT` — number of static few-shot examples (0-3)
- `PROMPT_PLANNING` — ask the model to plan tables/joins as SQL comments before the query
- `PROMPT_STRICT_OUTPUT` — emphatic "return only the SQL" output rules
- `RETRY_ON_ERROR` — one retry with the Postgres error fed back on failure

## Databases

The two modes never share a database.

| Mode | Database | Owner |
|---|---|---|
| Interactive App | `appdb` | Seeded from `db/init`; yours to replace |
| Benchmark | `tpch` | Created and rebuilt by the benchmark; not configurable |

`appdb` holds a small e-commerce dataset (customers, products, orders) that
loads automatically, so a fresh deploy always has something to query. Try:
*"Top 3 best-selling products"*. Reset it with `docker compose down -v`.

Benchmark runs drop and rebuild `tpch` and never touch `appdb` — or whatever
database you point app mode at.

**Upgrading from a pre-`appdb` deployment:** Postgres init scripts only run on a
fresh data volume, so `appdb` will be missing on an existing one. Run
`docker compose down -v` once to reseed. Benchmark mode needs no such step: it
creates `tpch` itself.

## Safety

- Single-statement, SELECT-only SQL — DDL/DML rejected
- Runs inside a read-only database transaction
- 30s statement timeout, 10,000-row result cap
- Questions capped at 2000 characters

## External Database

App mode only. Point it at your own server:

```yaml
environment:
  <<: *config
  INTERACTIVE_APP_DATABASE_URL: postgresql://user:pass@192.168.1.10:5432/mydb
```

Remove the `postgres` service dependency in `compose.yml`. For a host database,
add `extra_hosts: ["host.docker.internal:host-gateway"]` to `app`.

Benchmark mode has no equivalent knob — its database is pinned in code, so a
benchmark run can never load TPC-H into your data.

## Benchmark Mode

```bash
docker compose exec ollama pull-models benchmark
docker compose --profile benchmark up --build --no-log-prefix --attach benchmark benchmark
```

The benchmark builds its dataset in the `tpch` database on the bundled Postgres
server, independently of whatever app mode is connected to.

Runs a six-stage evaluation pipeline against TPC-H, scoring generated SQL (Result F1, AST similarity) across the models/seeds/queries set via `BENCHMARK_MODELS`, `BENCHMARK_NUM_SEEDS`, and `BENCHMARK_QUERY_IDS` above:

1. **Data Generation** — generate (or reuse cached) TPC-H data at the configured scale factor.
2. **Validation** — confirm the expected question/query files are present.
3. **Database Setup** — load the schema, data, and indexes if the database isn't already populated.
4. **Answer Generation** — execute the reference SQL to produce ground-truth answers.
5. **Per-model Generation, Execution & Scoring** — for each model in `BENCHMARK_MODELS`: generate SQL via the LLM, execute it, and score it against the ground truth.
6. **Cross-Model Comparison & Archiving** — when multiple models are configured, compare them side by side; archive the run to `benchmark/results/<timestamp>/` with a manifest describing the run.

## GPU Acceleration

```bash
docker compose -f compose.yml -f compose.nvidia.yml up -d   # NVIDIA
docker compose -f compose.yml -f compose.amd.yml up -d      # AMD (ROCm)
```
