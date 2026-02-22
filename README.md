# LLM Text-to-Query

Convert natural language to SQL queries using local LLMs.

## Quick Start

```bash
# Start all services
docker compose up -d

# Enter interactive REPL
docker compose exec app uv run llm-query
```

## Commands

| Command | Purpose |
|---------|---------|
| `docker compose up -d` | Start services (ollama, postgres, app) |
| `docker compose exec app uv run llm-query` | Start interactive REPL |
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

The automated pipeline:
1. Generates TPC-H test data
2. Loads database schema
3. Processes 22 questions through LLM
4. Saves SQL to `benchmark/queries/`
5. Shuts down automatically

## Requirements

- Docker Compose
- 8GB RAM (for 7B models)

## License

Apache 2.0
