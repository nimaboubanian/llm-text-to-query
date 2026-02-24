# LLM Text-to-Query

Convert natural language to SQL queries using local LLMs.

## Quick Start

```bash
# Start all services
docker compose up -d

# Enter interactive REPL
docker compose exec app uv run text2query
```

## Commands

| Command | Purpose |
|---------|---------|
| `docker compose up -d` | Start services (ollama, postgres, app) |
| `docker compose exec app uv run text2query` | Start interactive REPL |
| `docker compose --profile benchmark up` | Run automated TPC-H benchmark |
| `docker compose up -d --build app` | Rebuild after code changes |
| `docker compose logs -f app` | View app logs |
| `docker compose down` | Stop all services |
| `docker compose down -v` | Stop and remove all data volumes |

## Configuration

Create `config.yaml` (optional) to override defaults:
```yaml
default_model: qwen2.5-coder:7b
temperature: 0.1
max_tokens: 2048
```

## Benchmark

The automated TPC-H benchmark pipeline runs in three phases:

**Phase 1 — Setup & Validation**
1. Generates TPC-H test data (with caching)
2. Loads database schema, data, and indexes
3. Generates ground truth answer CSVs from reference queries

**Phase 2 — LLM Query Generation & Execution**
4. Sends 22 natural language questions to the LLM with the database schema
5. Executes LLM-generated SQL against the database

**Phase 3 — Analysis & Archiving**
6. Evaluates each query across four similarity layers:
   - **Result-set F1** — precision/recall on CSV row multisets
   - **AST similarity** — structural diff via sqlglot
   - **Component F1** — per-clause comparison (SELECT, FROM+JOIN, WHERE, etc.)
   - **Token Jaccard** — word-level overlap as fallback
7. Generates per-query and summary reports to `benchmark/answers/report/`
8. Archives the full session to `benchmark/results/YYYY-MM-DD_HH-MM-SS/`

## Requirements

- Docker Compose
- 8GB RAM (for 7B models)

## License

Apache 2.0
