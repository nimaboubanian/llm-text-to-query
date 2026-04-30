# LLM Text-to-Query

Convert natural language to SQL queries using local LLMs. Using TPC-H benchmark to evaluate the models.

## Quick Start

```bash
# Start services
docker compose up -d

# Pull models (first run only)
docker compose exec ollama pull-models chat

# Enter interactive mode
docker compose exec app text2query
```

## Configuration

All user-configurable settings are at the top of `compose.yml` in the `x-config` block:

```yaml
x-config: &config
  DEFAULT_MODEL:       "qwen2.5-coder:7b"     # SQL generation model
  FRONTDESK_MODEL:     "qwen2.5:3b"           # Intent routing model
  BENCHMARK_MODELS:    "llama3.2:3b,qwen2.5-coder:7b"
  BENCHMARK_NUM_SEEDS: "1" # Number of repetitation for more reliable results
```

After changing models, recreate the Ollama container to pull them:

```bash
docker compose up -d --force-recreate ollama
docker compose logs -f ollama   # watch download progress
```

## Mini Database

A simple e-commerce database (customers, products, orders) loads automatically for testing.

**Example queries:** "What are the customers' names?", "Top 3 best-selling products", "Show customers who spent more than $500 total"

Reset with `docker compose --profile benchmark down -v`.

## REPL Commands

| Command | Description |
|---|---|
| `/help` | Show available commands |
| `/schema` | Display the database schema |
| `/sql` | Display the SQL query |
| `/model` | List available models and the active one |
| `/model <name>` | Switch to a different model |
| `/quit` | Exit |

## External Database

Edit `DATABASE_URL` in the `app` service in `compose.yml` and remove the `postgres` dependency:

```yaml
environment:
  <<: *config
  DATABASE_URL: postgresql://user:pass@192.168.1.10:5432/mydb
```

For databases on the Docker host, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the `app` service.

## Benchmark

Edit `BENCHMARK_MODELS` in the `x-config` block of `compose.yml` to choose which models to compare (comma-separated, up to 3). Then pull them and run:

```bash
docker compose exec ollama pull-models benchmark
docker compose --profile benchmark up --build orchestrator
```

If you haven't changed `BENCHMARK_MODELS`, the benchmark runs with the default model — just make sure you've already run `pull-models chat`.

Runs a three-phase TPC-H pipeline: **Setup** (data generation, schema loading) → **Generation** (LLM query generation and execution) → **Analysis** (similarity metrics, reports, archiving).

### Evaluation Metrics

| Metric | Purpose |
|---|---|
| **Result F1** | Primary correctness — did the query produce the right data? |
| **AST Similarity** | Structural closeness of SQL to reference |
| **Clause Scores** | Per-clause breakdown (SELECT, WHERE, etc.) |
| **Composite** | Weighted aggregate: F1 (60%), AST (40%) |

### Multi-Seed Mode

Set `BENCHMARK_NUM_SEEDS` in `x-config` to run each query multiple times with different random seeds for statistical robustness (mean, std, 95% CI).

### Multi-Model Mode

Uncomment `BENCHMARK_MODELS` in `x-config` to compare up to 3 models side-by-side. Output includes per-model reports plus `comparison.md` and `results.csv`.

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
uv run pytest -v            # run all 99 tests
```

### Project Structure

```
app/src/text2query/
  core/config.py          # Centralized configuration (env vars)
  llm/service.py          # Ollama streaming + SQL extraction
  llm/prompts.py          # Prompt templates
  database/executor.py    # SQL execution → DataFrame
  database/schema.py      # Schema introspection
  cli/repl.py             # Interactive REPL
  cli/frontdesk.py        # Intent classification + summarization
  cli/style.py            # Nord-themed TUI
  benchmark/              # TPC-H benchmark pipeline
```
