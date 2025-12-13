# LLM Text-to-Query

A natural language to SQL/NoSQL query converter using local LLMs (Ollama) with multi-database support.

## Quick Start

```bash
# 1. Setup environment
cp .env.example .env

# 2. Start core services (app + LLM)
make up

# 3. Start with specific databases
make postgres    # + PostgreSQL
make mysql       # + MySQL
make all         # + All databases

# 4. Open the app
open http://localhost:8501
```

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make help` | Show all commands |
| `make up` | Start core services (app + Ollama) |
| `make dev` | Start with logs in terminal |
| `make postgres` | + PostgreSQL |
| `make mysql` | + MySQL |
| `make all` | + All databases |
| `make down` | Stop services (keeps data) |
| `make clean` | Stop and remove all volumes |
| `make logs` | View app logs |
| `make rebuild` | Rebuild app container |

## Configuration

### Environment Variables (.env)

Copy `.env.example` to `.env` and configure needed databases.

| Variable | Service | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | Ollama | LLM service URL |
| `POSTGRES_*` | PostgreSQL | DB credentials |
| `MYSQL_*` | MySQL | DB credentials |
| `MARIADB_*` | MariaDB | DB credentials |
| `MONGO_*` | MongoDB | DB credentials |
| `MSSQL_*` | SQL Server | DB credentials |
| `CLICKHOUSE_*` | ClickHouse | DB credentials |
| `NEO4J_*` | Neo4j | DB credentials |

## Services

| Service | Port | Health Check | Notes |
|---------|------|--------------|-------|
| App | 8501 | ✅ | Streamlit UI |
| Ollama | 11434 | ✅ | LLM API |
| PostgreSQL | 5432 | ✅ | SQL DB |
| MySQL | 3306 | ✅ | SQL DB |
| MariaDB | 3307 | ✅ | SQL DB |
| MongoDB | 27017 | ✅ | NoSQL DB |
| SQL Server | 1433 | ✅ | SQL DB |
| ClickHouse | 8123/9000 | ✅ | OLAP DB |
| Neo4j | 7474/7687 | ✅ | Graph DB |

## Features

- **Multi-Database**: SQL, NoSQL, Graph databases
- **LLM Selection**: Choose from 3 models (qwen2.5:7b, mistral:7b, llama3.2:3b)
- **Auto-Discovery**: Detect running databases
- **Persistent Data**: External volumes survive restarts
- **Health Checks**: All services monitored

## Usage

1. **Connect**: Auto-detect or manually add databases
2. **Chat**: Ask questions in natural language
3. **Query**: Get generated SQL/NoSQL queries

### Connection Examples

```text
PostgreSQL: postgresql://user:pass@postgres:5432/db
MySQL: mysql+pymysql://user:pass@mysql:3306/db
MongoDB: mongodb://admin:pass@mongodb:27017/db
```
