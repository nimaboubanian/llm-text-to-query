"""Configuration and environment variables for the application."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
# The .env file is located at the project root (3 levels up from this file)
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_ENV_PATH)

# =============================================================================
# Ollama LLM Configuration
# =============================================================================
OLLAMA_URL = os.getenv("OLLAMA_URL") or os.getenv("OLLAMA_HOST") or "http://localhost:11434"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))

# =============================================================================
# PostgreSQL Configuration
# =============================================================================
POSTGRES_USER = os.getenv("POSTGRES_USER", "user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))

# =============================================================================
# MySQL Configuration
# =============================================================================
MYSQL_USER = os.getenv("MYSQL_USER", "user")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "password")
MYSQL_ROOT_PASSWORD = os.getenv("MYSQL_ROOT_PASSWORD", "rootpassword")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "mysql")
MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))

# =============================================================================
# MariaDB Configuration
# =============================================================================
MARIADB_USER = os.getenv("MARIADB_USER", "user")
MARIADB_PASSWORD = os.getenv("MARIADB_PASSWORD", "password")
MARIADB_ROOT_PASSWORD = os.getenv("MARIADB_ROOT_PASSWORD", "rootpassword")
MARIADB_DATABASE = os.getenv("MARIADB_DATABASE", "mysql")
MARIADB_HOST = os.getenv("MARIADB_HOST", "mariadb")
MARIADB_PORT = int(os.getenv("MARIADB_PORT", "3306"))

# =============================================================================
# MongoDB Configuration
# =============================================================================
MONGO_USER = os.getenv("MONGO_INITDB_ROOT_USERNAME", "admin")
MONGO_PASSWORD = os.getenv("MONGO_INITDB_ROOT_PASSWORD", "password")
MONGO_HOST = os.getenv("MONGO_HOST", "mongodb")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_DATABASE = os.getenv("MONGO_DATABASE", "admin")

# =============================================================================
# SQL Server Configuration
# =============================================================================
MSSQL_USER = os.getenv("MSSQL_USER", "sa")
MSSQL_SA_PASSWORD = os.getenv("MSSQL_SA_PASSWORD", "YourStrong@Passw0rd")
MSSQL_DATABASE = os.getenv("MSSQL_DATABASE", "master")
MSSQL_HOST = os.getenv("MSSQL_HOST", "sqlserver")
MSSQL_PORT = int(os.getenv("MSSQL_PORT", "1433"))

# =============================================================================
# ClickHouse Configuration
# =============================================================================
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "default")
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))

# =============================================================================
# Neo4j Configuration
# =============================================================================
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_HOST = os.getenv("NEO4J_HOST", "neo4j")
NEO4J_PORT = int(os.getenv("NEO4J_PORT", "7687"))
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# =============================================================================
# Application Settings
# =============================================================================
APP_TITLE = os.getenv("APP_TITLE", "Text-to-SQL Chatbot")
DB_CONFIG_PATH = Path(os.getenv("DB_CONFIG_PATH", "/app/data/databases.json"))

