# LLM Text-to-Query

A natural language to SQL/NoSQL query converter using local LLMs (Ollama) with multi-database support.

## Quick Start

```bash
# 1. Setup environment
cp .env.example .env

# 2. Start core services (app + LLM only)
docker compose up -d

# 3. Start with specific databases
docker compose --profile postgres up -d           # + PostgreSQL
docker compose --profile postgres --profile mysql up -d  # + PostgreSQL & MySQL
docker compose --profile all up -d                # + All databases

# 4. Open the app
open http://localhost:8501
```

## Database Profiles

Only start the databases you need:

| Profile | Databases | Command |
|---------|-----------|---------|
| (none) | App + Ollama only | `docker compose up -d` |
| `postgres` | + PostgreSQL | `docker compose --profile postgres up -d` |
| `mysql` | + MySQL | `docker compose --profile mysql up -d` |
| `mariadb` | + MariaDB | `docker compose --profile mariadb up -d` |
| `mongodb` | + MongoDB | `docker compose --profile mongodb up -d` |
| `sqlserver` | + SQL Server | `docker compose --profile sqlserver up -d` |
| `clickhouse` | + ClickHouse | `docker compose --profile clickhouse up -d` |
| `neo4j` | + Neo4j | `docker compose --profile neo4j up -d` |
| `all` | All databases | `docker compose --profile all up -d` |

Combine profiles: `docker compose --profile postgres --profile mongodb up -d`

## Configuration

### Files Overview

| File | Purpose | Git Tracked |
|------|---------|-------------|
| `.env.example` | Template with all variables (copy this) | ✅ Yes |
| `.env` | Your actual credentials (edit this) | ❌ No |
| `docker-compose.yml` | Service definitions | ✅ Yes |
| `app/` | Application source code | ✅ Yes |
| `db/` | Example database schemas | ✅ Yes |

### Environment Variables (.env)

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

| Variable | Service | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | Ollama | LLM service URL |
| `POSTGRES_USER` | PostgreSQL | Database username |
| `POSTGRES_PASSWORD` | PostgreSQL | Database password |
| `POSTGRES_DB` | PostgreSQL | Database name |
| `MYSQL_ROOT_PASSWORD` | MySQL | Root password |
| `MYSQL_DATABASE` | MySQL | Database name |
| `MYSQL_USER` | MySQL | Database username |
| `MYSQL_PASSWORD` | MySQL | Database password |
| `MARIADB_*` | MariaDB | Same as MySQL |
| `MONGO_INITDB_ROOT_USERNAME` | MongoDB | Admin username |
| `MONGO_INITDB_ROOT_PASSWORD` | MongoDB | Admin password |
| `MSSQL_SA_PASSWORD` | SQL Server | SA password (complex required) |
| `CLICKHOUSE_USER` | ClickHouse | Username |
| `CLICKHOUSE_PASSWORD` | ClickHouse | Password |
| `CLICKHOUSE_DB` | ClickHouse | Default database |
| `NEO4J_USER` | Neo4j | Username |
| `NEO4J_PASSWORD` | Neo4j | Password |

## Services

| Service | Port | Description |
|---------|------|-------------|
| App | 8501 | Streamlit web interface |
| Ollama | 11434 | LLM API |
| PostgreSQL | 5432 | SQL database |
| MySQL | 3306 | SQL database |
| MariaDB | 3307 | SQL database |
| MongoDB | 27017 | NoSQL database |
| SQL Server | 1433 | SQL database |
| ClickHouse | 8123, 9000 | OLAP database |
| Neo4j | 7474, 7687 | Graph database |

## Usage

1. **Quick Connect**: Select from auto-detected running databases
2. **Add Manually**: Enter custom connection URLs
3. **Chat**: Ask questions in natural language

### Connection URL Examples

```text
PostgreSQL:  postgresql://user:password@postgres:5432/company_data
MySQL:       mysql+pymysql://user:password@mysql:3306/ecommerce_db
MariaDB:     mysql+pymysql://user:password@mariadb:3306/library_db
MongoDB:     mongodb://admin:password@mongodb:27017/blog_platform
SQLite:      sqlite:////app/data/mydb.db
SQL Server:  mssql+pymssql://sa:Password@sqlserver:1433/mydb
ClickHouse:  clickhouse://default:password@clickhouse:8123/analytics
Neo4j:       bolt://neo4j:password@neo4j:7687
```
