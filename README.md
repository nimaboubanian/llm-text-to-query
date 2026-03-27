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

**Phase 1 — Setup & Validation**

1. Generates/Validates TPC-H test data using `tpchgen-cli`
2. Loads database schema, data, and indexes
3. Generates ground truth answer CSVs from reference queries

**Phase 2 — LLM Query Generation & Execution**

4. Prompts natural language questions to the LLM with the database schema
5. Executes LLM-generated SQL against the database

**Phase 3 — Analysis & Archiving**

6. Evaluates each query using similarity criteria
7. Generates the reports to `benchmark/results/YYYY-MM-DD_HH-MM-SS/`

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
