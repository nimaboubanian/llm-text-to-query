"""Schema introspection helpers for various database types."""

from typing import Optional

from sqlalchemy import create_engine, inspect, text

try:
    from .database_config import DatabaseType
except ImportError:
    from database_config import DatabaseType

# SQL-based database types that use SQLAlchemy
SQL_DB_TYPES = {
    DatabaseType.POSTGRESQL,
    DatabaseType.MYSQL,
    DatabaseType.SQLITE,
    DatabaseType.MARIADB,
    DatabaseType.SQLSERVER,
    DatabaseType.CLICKHOUSE,
}


def get_database_schema_string(engine, db_type: DatabaseType = DatabaseType.POSTGRESQL):
    """Introspects the database to generate a DDL-like string for the LLM prompt."""
    try:
        if db_type in SQL_DB_TYPES:
            return _get_sql_schema(engine)
        if db_type == DatabaseType.MONGODB:
            return _get_mongodb_schema(engine)
        if db_type == DatabaseType.NEO4J:
            return _get_neo4j_schema(engine)
        return f"Schema introspection not yet implemented for {db_type.value}"
    except Exception as e:
        raise RuntimeError(f"Failed to introspect schema for {db_type.value}: {e}") from e


def _get_sql_schema(engine):
    """Get schema for SQL databases using SQLAlchemy."""
    inspector = inspect(engine)
    schema_strings = []

    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        col_descs = [f"{c['name']} ({c['type']})" for c in columns]

        fk_descs = [
            f"FOREIGN KEY ({', '.join(fk['constrained_columns'])}) "
            f"REFERENCES {fk['referred_table']}({', '.join(fk['referred_columns'])})"
            for fk in inspector.get_foreign_keys(table_name)
        ]

        table_desc = f"Table '{table_name}' has columns: {', '.join(col_descs)}"
        if fk_descs:
            table_desc += ". " + " ".join(fk_descs)
        schema_strings.append(table_desc)

    return "\n".join(schema_strings)


def _get_mongodb_schema(connection_url):
    """Get schema for MongoDB by sampling collections."""
    try:
        from pymongo import MongoClient  # pylint: disable=import-outside-toplevel

        client = MongoClient(connection_url)
        db_name = connection_url.split("/")[-1].split("?")[0] or "test"
        db = client[db_name]

        schema_strings = [
            (
                f"Collection '{name}' has fields: {', '.join(doc.keys())}"
                if (doc := db[name].find_one())
                else f"Collection '{name}' (empty)"
            )
            for name in db.list_collection_names()
        ]
        client.close()
        return "\n".join(schema_strings)
    except ImportError:
        return "MongoDB support requires 'pymongo' package."
    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"Error introspecting MongoDB schema: {e}"


def _get_neo4j_schema(connection_url):
    """Get schema for Neo4j by querying node labels, relationship types, and properties."""
    try:
        from neo4j import GraphDatabase  # pylint: disable=import-outside-toplevel

        # Parse bolt URL: bolt://user:pass@host:port
        url_parts = connection_url.replace("bolt://", "").split("@")
        auth = (
            tuple(url_parts[0].split(":")) if len(url_parts) > 1 else ("neo4j", "neo4j")
        )
        uri = f"bolt://{url_parts[-1]}"

        driver = GraphDatabase.driver(uri, auth=auth)
        schema_strings = []

        with driver.session() as session:
            # Get node labels and their properties
            labels = session.run("CALL db.labels()").value()
            for label in labels:
                props = session.run(
                    f"MATCH (n:`{label}`) WITH n LIMIT 1 RETURN keys(n) as keys"
                ).single()
                prop_list = props["keys"] if props else []
                schema_strings.append(
                    f"Node ':{label}' has properties: {', '.join(prop_list) or 'none'}"
                )

            # Get relationship types
            rel_types = session.run("CALL db.relationshipTypes()").value()
            for rel_type in rel_types:
                schema_strings.append(f"Relationship ':{rel_type}'")

        driver.close()
        return "\n".join(schema_strings) or "Empty graph database"
    except ImportError:
        return "Neo4j support requires 'neo4j' package."
    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"Error introspecting Neo4j schema: {e}"


def create_engine_for_database(db_url: str, db_type: DatabaseType):
    """Create appropriate engine/connection for database type."""
    if db_type in SQL_DB_TYPES:
        return create_engine(db_url)
    if db_type == DatabaseType.MONGODB:
        return db_url  # MongoDB URL handled separately
    if db_type == DatabaseType.NEO4J:
        return db_url  # Neo4j URL handled separately
    raise ValueError(f"Unsupported database type: {db_type.value}")


def validate_database_connection(
    db_url: str, db_type: DatabaseType
) -> tuple[bool, Optional[str]]:
    """Validate database connection. Returns (success, error_message)."""
    try:
        if db_type in SQL_DB_TYPES:
            engine = create_engine(db_url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return True, None
        if db_type == DatabaseType.MONGODB:
            from pymongo import MongoClient  # pylint: disable=import-outside-toplevel

            client = MongoClient(db_url, serverSelectionTimeoutMS=5000)
            client.server_info()
            client.close()
            return True, None
        if db_type == DatabaseType.NEO4J:
            from neo4j import GraphDatabase  # pylint: disable=import-outside-toplevel

            url_parts = db_url.replace("bolt://", "").split("@")
            auth = (
                tuple(url_parts[0].split(":"))
                if len(url_parts) > 1
                else ("neo4j", "neo4j")
            )
            uri = f"bolt://{url_parts[-1]}"
            driver = GraphDatabase.driver(uri, auth=auth)
            driver.verify_connectivity()
            driver.close()
            return True, None
        return False, f"Unsupported database type: {db_type.value}"
    except ImportError:
        return False, "Required database driver not installed"
    except Exception as e:  # pylint: disable=broad-exception-caught
        return False, str(e)
