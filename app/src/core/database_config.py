"""Database configuration management for multi-database support."""

import json
import os
import re
import socket
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


# Path for storing database configurations
DB_CONFIG_PATH = Path(os.getenv("DB_CONFIG_PATH", "/app/data/databases.json"))


class DatabaseType(Enum):
    """Supported database types."""

    POSTGRESQL = "PostgreSQL"
    MYSQL = "MySQL"
    SQLITE = "SQLite"
    MONGODB = "MongoDB"
    MARIADB = "MariaDB"
    SQLSERVER = "SQL Server"
    CLICKHOUSE = "ClickHouse"
    NEO4J = "Neo4j"


# Mapping of type string to DatabaseType enum
_TYPE_STR_MAP = {t.name: t for t in DatabaseType}


@dataclass
class DatabaseServer:
    """A database server endpoint."""

    name: str
    db_type: DatabaseType
    host: str
    port: int
    user: str
    password: str
    default_db: str  # Used for initial connection to list databases


# Known database server endpoints - credentials from environment
def _get_known_servers() -> list[DatabaseServer]:
    """Build server list using environment variables."""
    return [
        DatabaseServer(
            "PostgreSQL",
            DatabaseType.POSTGRESQL,
            "postgres",
            5432,
            os.getenv("POSTGRES_USER", "user"),
            os.getenv("POSTGRES_PASSWORD", "password"),
            os.getenv("POSTGRES_DB", "postgres"),
        ),
        DatabaseServer(
            "MySQL",
            DatabaseType.MYSQL,
            "mysql",
            3306,
            os.getenv("MYSQL_USER", "user"),
            os.getenv("MYSQL_PASSWORD", "password"),
            os.getenv("MYSQL_DATABASE", "mysql"),
        ),
        DatabaseServer(
            "MariaDB",
            DatabaseType.MARIADB,
            "mariadb",
            3306,
            os.getenv("MARIADB_USER", "user"),
            os.getenv("MARIADB_PASSWORD", "password"),
            os.getenv("MARIADB_DATABASE", "mysql"),
        ),
        DatabaseServer(
            "MongoDB",
            DatabaseType.MONGODB,
            "mongodb",
            27017,
            os.getenv("MONGO_INITDB_ROOT_USERNAME", "admin"),
            os.getenv("MONGO_INITDB_ROOT_PASSWORD", "password"),
            "admin",
        ),
        DatabaseServer(
            "SQL Server",
            DatabaseType.SQLSERVER,
            "sqlserver",
            1433,
            os.getenv("MSSQL_USER", "sa"),
            os.getenv("MSSQL_SA_PASSWORD", "Password123!"),
            os.getenv("MSSQL_DATABASE", "master"),
        ),
        DatabaseServer(
            "ClickHouse",
            DatabaseType.CLICKHOUSE,
            "clickhouse",
            8123,
            os.getenv("CLICKHOUSE_USER", "default"),
            os.getenv("CLICKHOUSE_PASSWORD", ""),
            os.getenv("CLICKHOUSE_DATABASE", "default"),
        ),
        DatabaseServer(
            "Neo4j",
            DatabaseType.NEO4J,
            "neo4j",
            7687,
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "password"),
            "neo4j",
        ),
    ]


def _check_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a port is open on a host."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, socket.error, OSError):
        return False


def discover_available_servers() -> list[DatabaseServer]:
    """Probe known server endpoints and return available ones."""
    return [s for s in _get_known_servers() if _check_port_open(s.host, s.port)]


def get_server_databases(server: DatabaseServer) -> list[str]:
    """List available databases on a server."""
    try:
        if server.db_type == DatabaseType.MONGODB:
            from pymongo import MongoClient  # pylint: disable=import-outside-toplevel

            client = MongoClient(
                host=server.host,
                port=server.port,
                username=server.user,
                password=server.password,
                serverSelectionTimeoutMS=2000,
            )
            dbs = [
                db
                for db in client.list_database_names()
                if db not in ("admin", "config", "local")
            ]
            client.close()
            return dbs

        if server.db_type == DatabaseType.NEO4J:
            # Neo4j doesn't have multiple databases in community edition
            return [server.default_db]

        from sqlalchemy import create_engine, text  # pylint: disable=import-outside-toplevel

        url = build_connection_url(server, server.default_db)

        # Database listing queries per type
        queries = {
            DatabaseType.POSTGRESQL: (
                "SELECT datname FROM pg_database "
                "WHERE datistemplate = false AND datname NOT IN ('postgres')"
            ),
            DatabaseType.MYSQL: "SHOW DATABASES",
            DatabaseType.MARIADB: "SHOW DATABASES",
            DatabaseType.SQLSERVER: (
                "SELECT name FROM sys.databases "
                "WHERE name NOT IN ('master', 'tempdb', 'model', 'msdb')"
            ),
            DatabaseType.CLICKHOUSE: "SHOW DATABASES",
        }

        query = queries.get(server.db_type)
        if not query:
            return [server.default_db]

        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            result = conn.execute(text(query))
            dbs = [row[0] for row in result]
        engine.dispose()

        # Filter system databases
        system_dbs = {
            DatabaseType.MYSQL: {
                "information_schema",
                "mysql",
                "performance_schema",
                "sys",
            },
            DatabaseType.MARIADB: {
                "information_schema",
                "mysql",
                "performance_schema",
                "sys",
            },
            DatabaseType.CLICKHOUSE: {
                "system",
                "information_schema",
                "INFORMATION_SCHEMA",
            },
        }
        if server.db_type in system_dbs:
            dbs = [db for db in dbs if db not in system_dbs[server.db_type]]

        return dbs if dbs else [server.default_db]
    except Exception:
        return [server.default_db]


def build_connection_url(server: DatabaseServer, database: str) -> str:
    """Build a connection URL for a specific database on a server."""
    u, p, h, port = server.user, server.password, server.host, server.port

    url_patterns = {
        DatabaseType.MONGODB: f"mongodb://{u}:{p}@{h}:{port}/{database}",
        DatabaseType.POSTGRESQL: f"postgresql://{u}:{p}@{h}:{port}/{database}",
        DatabaseType.MYSQL: f"mysql+pymysql://{u}:{p}@{h}:{port}/{database}",
        DatabaseType.MARIADB: f"mysql+pymysql://{u}:{p}@{h}:{port}/{database}",
        DatabaseType.SQLSERVER: f"mssql+pymssql://{u}:{p}@{h}:{port}/{database}",
        DatabaseType.CLICKHOUSE: f"clickhouse://{u}:{p}@{h}:{port}/{database}",
        DatabaseType.NEO4J: f"bolt://{u}:{p}@{h}:{port}",
    }
    return url_patterns.get(
        server.db_type, f"postgresql://{u}:{p}@{h}:{port}/{database}"
    )


@dataclass
class DatabaseConfig:
    """Database connection configuration."""

    name: str
    db_type: DatabaseType
    url: str
    description: str = ""

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "name": self.name,
            "db_type": self.db_type.name,
            "url": self.url,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DatabaseConfig":
        """Create from dict."""
        return cls(
            name=data["name"],
            db_type=_TYPE_STR_MAP.get(data["db_type"], DatabaseType.POSTGRESQL),
            url=data["url"],
            description=data.get("description", ""),
        )


class DatabaseConfigManager:
    """Manages database configurations stored in JSON file."""

    def __init__(self):
        self.databases = self._load_databases()

    def _load_databases(self) -> dict[str, DatabaseConfig]:
        """Load databases from JSON file."""
        if not DB_CONFIG_PATH.exists():
            return {}
        try:
            data = json.loads(DB_CONFIG_PATH.read_text(encoding="utf-8"))
            return {k: DatabaseConfig.from_dict(v) for k, v in data.items()}
        except (json.JSONDecodeError, KeyError):
            return {}

    def _save_databases(self) -> None:
        """Save databases to JSON file."""
        DB_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v.to_dict() for k, v in self.databases.items()}
        DB_CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add_database(
        self, name: str, db_type: DatabaseType, url: str, description: str = ""
    ) -> str:
        """Add a database configuration and persist to file."""
        base_key = re.sub(r"[^a-z0-9]", "_", name.lower()).strip("_")
        config_key = base_key
        counter = 1
        while config_key in self.databases:
            config_key = f"{base_key}_{counter}"
            counter += 1

        self.databases[config_key] = DatabaseConfig(name, db_type, url, description)
        self._save_databases()
        return config_key

    def remove_database(self, config_key: str) -> bool:
        """Remove a database configuration and update file."""
        if self.databases.pop(config_key, None) is not None:
            self._save_databases()
            return True
        return False

    def get_all_databases(self) -> dict[str, DatabaseConfig]:
        """Get all available database configurations."""
        return self.databases

    def get_database(self, config_key: str) -> Optional[DatabaseConfig]:
        """Get a specific database configuration."""
        return self.databases.get(config_key)

    def get_database_display_names(self) -> list[tuple[str, str]]:
        """Get list of (config_key, display_name) tuples for UI."""
        return [(k, c.name) for k, c in self.databases.items()]
