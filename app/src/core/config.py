"""Configuration and environment variables for the application."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_ENV_PATH)


def _env(key: str, default: str = "") -> str:
    """Get environment variable with default."""
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    """Get integer environment variable with default."""
    return int(os.getenv(key, str(default)))


# =============================================================================
# Ollama LLM Configuration
# =============================================================================
OLLAMA_URL = _env("OLLAMA_URL") or _env("OLLAMA_HOST") or "http://localhost:11434"
OLLAMA_MODEL = _env("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = _env_int("OLLAMA_TIMEOUT", 120)

# =============================================================================
# Database Configurations (host, port, user, password, database)
# =============================================================================
POSTGRES_HOST, POSTGRES_PORT = _env("POSTGRES_HOST", "postgres"), _env_int("POSTGRES_PORT", 5432)
POSTGRES_USER, POSTGRES_PASSWORD = _env("POSTGRES_USER", "user"), _env("POSTGRES_PASSWORD", "password")
POSTGRES_DB = _env("POSTGRES_DB", "postgres")

MYSQL_HOST, MYSQL_PORT = _env("MYSQL_HOST", "mysql"), _env_int("MYSQL_PORT", 3306)
MYSQL_USER, MYSQL_PASSWORD = _env("MYSQL_USER", "user"), _env("MYSQL_PASSWORD", "password")
MYSQL_ROOT_PASSWORD = _env("MYSQL_ROOT_PASSWORD", "rootpassword")
MYSQL_DATABASE = _env("MYSQL_DATABASE", "mysql")

MARIADB_HOST, MARIADB_PORT = _env("MARIADB_HOST", "mariadb"), _env_int("MARIADB_PORT", 3306)
MARIADB_USER, MARIADB_PASSWORD = _env("MARIADB_USER", "user"), _env("MARIADB_PASSWORD", "password")
MARIADB_ROOT_PASSWORD = _env("MARIADB_ROOT_PASSWORD", "rootpassword")
MARIADB_DATABASE = _env("MARIADB_DATABASE", "mysql")

MONGO_HOST, MONGO_PORT = _env("MONGO_HOST", "mongodb"), _env_int("MONGO_PORT", 27017)
MONGO_USER = _env("MONGO_INITDB_ROOT_USERNAME", "admin")
MONGO_PASSWORD = _env("MONGO_INITDB_ROOT_PASSWORD", "password")
MONGO_DATABASE = _env("MONGO_DATABASE", "admin")

MSSQL_HOST, MSSQL_PORT = _env("MSSQL_HOST", "sqlserver"), _env_int("MSSQL_PORT", 1433)
MSSQL_USER = _env("MSSQL_USER", "sa")
MSSQL_SA_PASSWORD = _env("MSSQL_SA_PASSWORD", "YourStrong@Passw0rd")
MSSQL_DATABASE = _env("MSSQL_DATABASE", "master")

CLICKHOUSE_HOST, CLICKHOUSE_PORT = _env("CLICKHOUSE_HOST", "clickhouse"), _env_int("CLICKHOUSE_PORT", 8123)
CLICKHOUSE_USER, CLICKHOUSE_PASSWORD = _env("CLICKHOUSE_USER", "default"), _env("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DB = _env("CLICKHOUSE_DB", "default")

NEO4J_HOST, NEO4J_PORT = _env("NEO4J_HOST", "neo4j"), _env_int("NEO4J_PORT", 7687)
NEO4J_USER, NEO4J_PASSWORD = _env("NEO4J_USER", "neo4j"), _env("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = _env("NEO4J_DATABASE", "neo4j")

# =============================================================================
# Application Settings
# =============================================================================
APP_TITLE = _env("APP_TITLE", "Text-to-SQL Chatbot")
DB_CONFIG_PATH = Path(_env("DB_CONFIG_PATH", "/app/data/databases.json"))

