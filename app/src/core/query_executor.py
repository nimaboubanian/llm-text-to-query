"""Query execution service for various database types."""

import pandas as pd
from sqlalchemy import text

from core.database_config import DatabaseType

# SQL-based database types
SQL_DB_TYPES = frozenset({
    DatabaseType.POSTGRESQL,
    DatabaseType.MYSQL,
    DatabaseType.SQLITE,
    DatabaseType.MARIADB,
    DatabaseType.SQLSERVER,
    DatabaseType.CLICKHOUSE,
})


def execute_sql_query(engine, sql_query: str, db_type: DatabaseType):
    """
    Execute the SQL query and return results as a DataFrame.

    Returns:
        DataFrame with results, or error message string
    """
    try:
        if db_type in SQL_DB_TYPES:
            return _execute_sqlalchemy_query(engine, sql_query)
        if db_type == DatabaseType.MONGODB:
            return "MongoDB query execution not yet implemented"
        if db_type == DatabaseType.NEO4J:
            return _execute_neo4j_query(engine, sql_query)
        return f"Query execution not supported for {db_type.value}"
    except Exception as e:  # pylint: disable=broad-exception-caught
        return str(e)


def _execute_sqlalchemy_query(engine, sql_query: str) -> pd.DataFrame:
    """Execute query using SQLAlchemy engine."""
    with engine.connect() as conn:
        result = conn.execute(text(sql_query))
        rows = result.fetchall()
        columns = result.keys()
        return pd.DataFrame(rows, columns=columns)


def _execute_neo4j_query(connection_url: str, cypher_query: str):
    """
    Execute a Cypher query on Neo4j and return results as DataFrame.

    Args:
        connection_url: Bolt URL in format bolt://user:pass@host:port
        cypher_query: Cypher query to execute

    Returns:
        DataFrame with results, or error message string
    """
    try:
        from neo4j import GraphDatabase  # pylint: disable=import-outside-toplevel

        # Parse bolt URL: bolt://user:pass@host:port
        url_parts = connection_url.replace("bolt://", "").split("@")
        auth = (
            tuple(url_parts[0].split(":")) if len(url_parts) > 1 else ("neo4j", "neo4j")
        )
        uri = f"bolt://{url_parts[-1]}"

        driver = GraphDatabase.driver(uri, auth=auth)
        with driver.session() as session:
            result = session.run(cypher_query)
            records = [dict(record) for record in result]
            driver.close()

            if records:
                return pd.DataFrame(records)
            return pd.DataFrame()
    except ImportError:
        return "Neo4j support requires 'neo4j' package."
    except Exception as e:  # pylint: disable=broad-exception-caught
        return str(e)
