# LLM Text-to-Query

Convert natural language to SQL queries using local LLMs.

## Quick Start

```bash
# Start all services (includes default mini database)
docker compose up -d

# Enter interactive REPL
docker compose exec app uv run text2query
```

## Default Mini Database

A simple e-commerce database loads automatically on first startup for testing:

| Table | Rows | Description |
|-------|------|-------------|
| `customers` | 30 | Customer profiles (name, email, city) |
| `products` | 20 | Product catalog (name, category, price, cost, stock) |
| `orders` | 100 | Order records (customer, product, quantity, date, total) |

**Example queries to try:**

- "What are the customers' names?"
- "Which product has the highest price?"
- "How many orders does each customer have?"
- "Show total sales per product"
- "Which customers are from New York?"
- "What products have never been ordered?"
- "Top 3 best-selling products"
- "Show customers who spent more than $500 total"

The mini database persists in the Docker volume. To reset it, run `docker compose down -v`.

## REPL Commands

| Command | Description |
|---|---|
| `/help` | Show available commands |
| `/schema` | Display the database schema |
| `/model` | List available models and the active one |
| `/model <name>` | Switch to a different model |
| `/quit` | Exit |

## Using an External Database

To connect to a PostgreSQL database outside of Docker, edit `DATABASE_URL` in the `app` service in `compose.yml` and remove the `postgres` dependency. For example:

```yaml
# compose.yml — app service
environment:
  <<: *common-env
  DATABASE_URL: postgresql://user:pass@192.168.1.10:5432/mydb
# depends_on:          # remove or comment out postgres dependency
#   ollama:
#     condition: service_healthy
#   postgres:
#     condition: service_healthy
```

If the external database runs on the Docker host machine (not inside a container), add `extra_hosts` to the `app` service and use `host.docker.internal` as the hostname:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

The internal `postgres` service can be removed from `compose.yml` when unused.

## Benchmark

```bash
# Start benchmark
docker compose --profile benchmark up --build orchestrator
```

The automated TPC-H benchmark runs in three phases:

**Phase 1 — Setup & Validation** (runs once per session)

1. Generates/Validates TPC-H test data using `tpchgen-cli`
2. Loads database schema, data, and indexes
3. Generates ground truth answer CSVs from reference queries

**Phase 2 — LLM Query Generation & Execution** (per model × per seed)

4. Prompts natural language questions to the LLM with the database schema
5. Executes LLM-generated SQL against the database

**Phase 3 — Analysis & Archiving**

6. Evaluates each query using similarity metrics
7. Generates reports and archives everything to `benchmark/results/YYYY-MM-DD_HH-MM-SS/`

### Evaluation Metrics

| Metric | Purpose |
|---|---|
| **Result F1** | Did the query produce the correct data? Primary correctness measure. |
| **AST Similarity** | How structurally close is the SQL to the reference? |
| **BLEU** | N-gram overlap between SQL token sequences. |
| **Token Jaccard** | Set-based keyword overlap between queries. |
| **Clause Scores** | Per-clause breakdown (SELECT, WHERE, etc.) to identify which parts failed. |
| **Error Category** | Classifies execution failures (SyntaxError, SchemaMismatch, RuntimeError, Timeout). |
| **Composite** | Weighted aggregate of F1 (45%), AST (25%), Embed (20%), BLEU (10%) for ranking. |

### Multi-Seed Mode

Run each query multiple times with different random seeds to get statistically robust results (mean, standard deviation, 95% confidence intervals).

**Enable:** in `compose.yml`, set `BENCHMARK_NUM_SEEDS` under the `x-model-env` or orchestrator environment:

```yaml
BENCHMARK_NUM_SEEDS: "5"   # default — 5 seeds per query
```

Set to `"1"` to disable and run each query once (single-seed).

**Output structure (multi seeds):**

```
benchmark/results/YYYY-MM-DD_HH-MM-SS/
  queries/
    seed_1/01.sql … 22.sql
    seed_2/01.sql … 22.sql
    …
  answers/
    seed_1/01.csv … 22.csv
    …
  report/
    summary.md          # mean±std and 95% CI for all metrics
    per_query/01.md … 22.md
```

### Multi-Model Mode

Run the full benchmark (including multiple seeds) for up to 3 models and get a side-by-side comparison report.

**Enable:** in `compose.yml`, uncomment `BENCHMARK_MODELS` in the `x-model-env` block and list the models you want to compare:

```yaml
x-model-env: &model-env
  DEFAULT_MODEL: qwen2.5-coder:7b
  BENCHMARK_MODELS: "llama3.2:3b,qwen2.5-coder:7b,deepseek-coder:6.7b"
```

Then recreate the Ollama container so it pulls the new models:

```bash
docker compose up -d --force-recreate ollama
docker compose logs -f ollama   # watch model download progress
```

Then run the benchmark as usual:

```bash
docker compose --profile benchmark up --build orchestrator
```

**Output structure (multi models, multi seeds):**

```
benchmark/results/YYYY-MM-DD_HH-MM-SS/
  queries/
    llama3.2_3b/seed_1/01.sql …
    qwen2.5-coder_7b/seed_1/01.sql …
    deepseek-coder_6.7b/seed_1/01.sql …
  answers/
    llama3.2_3b/seed_1/01.csv …
    …
  report/
    llama3.2_3b/summary.md
    qwen2.5-coder_7b/summary.md
    deepseek-coder_6.7b/summary.md
    comparison.md       # side-by-side F1 and composite scores per query
    results.csv         # all raw results (model, query, seed, metrics)
```

`results.csv` can be loaded directly into pandas, R, or Excel for further analysis.

**To disable multi-model mode:** comment out `BENCHMARK_MODELS` and recreate ollama:

```yaml
x-model-env: &model-env
  DEFAULT_MODEL: qwen2.5-coder:7b
  # BENCHMARK_MODELS: "llama3.2:3b,qwen2.5-coder:7b,deepseek-coder:6.7b"
```

```bash
docker compose up -d --force-recreate ollama
```

The benchmark will then run with `DEFAULT_MODEL` only.

## GPU Acceleration

By default, Ollama runs on CPU. To use a GPU, pass a compose override file — all your settings in `compose.yml` (models, seeds, etc.) are preserved.

### NVIDIA GPU

**Prerequisite:** install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).

```bash
# Start with NVIDIA GPU
docker compose -f compose.yml -f compose.nvidia.yml up -d

# Benchmark with GPU
docker compose -f compose.yml -f compose.nvidia.yml --profile benchmark up --build orchestrator
```

### AMD GPU

**Prerequisite:** install [AMD ROCm drivers](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/).

```bash
# Start with AMD GPU
docker compose -f compose.yml -f compose.amd.yml up -d

# Benchmark with GPU
docker compose -f compose.yml -f compose.amd.yml --profile benchmark up --build orchestrator
```
