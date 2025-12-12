"""Main application entry point and business logic for LLM Text-to-Query chatbot."""

import os
import re
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from sqlalchemy import text

from dotenv import load_dotenv

try:
    from .database_config import DatabaseType
    from .ui import init_session_state, render_sidebar, render_main_chat_interface
except ImportError:
    from database_config import DatabaseType
    from ui import init_session_state, render_sidebar, render_main_chat_interface

# Environment Variables
load_dotenv(Path(__file__).resolve().parents[3] / ".env")
OLLAMA_URL = os.getenv("OLLAMA_URL") or os.getenv("OLLAMA_HOST") or "http://localhost:11434"


def get_sql_from_llm(
    user_query, schema_str, db_type: DatabaseType = DatabaseType.POSTGRESQL
):
    """Sends the prompt to Ollama and returns the generated SQL."""

    # Map database types to SQL dialects
    dialect_map = {
        DatabaseType.POSTGRESQL: "PostgreSQL",
        DatabaseType.MYSQL: "MySQL",
        DatabaseType.MARIADB: "MariaDB (MySQL-compatible)",
        DatabaseType.SQLITE: "SQLite",
        DatabaseType.MONGODB: "MongoDB (use MongoDB query syntax, not SQL)",
        DatabaseType.SQLSERVER: "Microsoft SQL Server (T-SQL)",
        DatabaseType.CLICKHOUSE: "ClickHouse SQL",
        DatabaseType.NEO4J: "Neo4j Cypher (graph query language, not SQL)",
    }
    dialect = dialect_map.get(db_type, "SQL")

    prompt = (
        f"You are a {dialect} query generator. "
        f"Given the following database schema:\n{schema_str}\n\n"
        f"Generate a query to answer: {user_query}\n\n"
        f"Rules:\n"
        f"- Return ONLY the query, nothing else\n"
        f"- No explanations, no comments, no markdown\n"
        f"- Only use tables and columns from the schema above\n"
        f"- Use {dialect} syntax"
    )

    payload = {"model": "qwen2.5:7b", "prompt": prompt, "stream": False}

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate", json=payload, timeout=120
        )

        if response.status_code == 404:
            return (
                None,
                "Model 'qwen2.5:7b' not found. "
                "Please run: docker exec ollama-model-init ollama pull qwen2.5:7b",
            )

        if response.status_code != 200:
            return None, f"LLM API error: {response.status_code} - {response.text}"

        response_json = response.json()
        sql_query = response_json.get("response", "").strip()

        if not sql_query:
            return None, "LLM returned an empty response"

        # Clean SQL query - extract only the first SQL statement
        sql_query = clean_sql_response(sql_query)

        if not sql_query:
            return None, "Could not extract a valid SQL query from LLM response"

        return sql_query, None

    except requests.exceptions.Timeout:
        return (
            None,
            "LLM request timed out. The model might be loading, please try again.",
        )
    except requests.exceptions.RequestException as e:
        return None, f"Failed to connect to LLM: {e}"


def clean_sql_response(response):
    """Extract clean SQL from LLM response that may contain markdown or explanations."""
    # Remove markdown code blocks
    # Match ```sql ... ``` or ``` ... ```
    code_block_pattern = r"```(?:sql)?\s*(.*?)```"
    matches = re.findall(code_block_pattern, response, re.DOTALL | re.IGNORECASE)
    if matches:
        # Take the first code block
        return matches[0].strip()

    # If no code blocks, try to extract SELECT/INSERT/UPDATE/DELETE statement
    # Find the first SQL statement
    sql_pattern = r"(SELECT|INSERT|UPDATE|DELETE|WITH)\s+.*?;"
    match = re.search(sql_pattern, response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0).strip()

    # If no semicolon, try without it
    sql_pattern_no_semi = r"(SELECT|INSERT|UPDATE|DELETE|WITH)\s+[^;]*"
    match = re.search(sql_pattern_no_semi, response, re.DOTALL | re.IGNORECASE)
    if match:
        sql = match.group(0).strip()
        # Stop at common non-SQL patterns
        for stop_word in ["\n\nOR ", "\n\nNote:", "\n\nThis ", "\n\nIf ", "\n\n--"]:
            if stop_word in sql:
                sql = sql.split(stop_word)[0].strip()
        return sql

    # Last resort: return the first line if it looks like SQL
    first_line = response.split("\n")[0].strip()
    if first_line.upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
        return first_line

    return None


def execute_sql_query(engine, sql_query, db_type: DatabaseType):
    """Executes the SQL query and returns a DataFrame."""
    try:
        # SQL-based databases (SQLAlchemy)
        sql_types = [
            DatabaseType.POSTGRESQL,
            DatabaseType.MYSQL,
            DatabaseType.SQLITE,
            DatabaseType.MARIADB,
            DatabaseType.SQLSERVER,
            DatabaseType.CLICKHOUSE,
        ]
        if db_type in sql_types:
            with engine.connect() as conn:
                result = conn.execute(text(sql_query))
                rows = result.fetchall()
                columns = result.keys()
                df = pd.DataFrame(rows, columns=columns)
                return df
        elif db_type == DatabaseType.MONGODB:
            # For MongoDB, the query would be different (not SQL)
            return "MongoDB query execution not yet implemented"
        elif db_type == DatabaseType.NEO4J:
            # Neo4j uses Cypher, handle separately
            return _execute_neo4j_query(engine, sql_query)
        else:
            return f"Query execution not supported for {db_type.value}"
    except Exception as e:  # pylint: disable=broad-exception-caught
        return str(e)


def _execute_neo4j_query(connection_url: str, cypher_query: str):
    """Execute a Cypher query on Neo4j and return results as DataFrame."""
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


def main():
    """Main Streamlit application entry point."""
    # Page Config (must be first Streamlit command)
    st.set_page_config(page_title="Text-to-SQL Chatbot", layout="wide")

    # Initialize session state
    init_session_state()

    # Render sidebar with all settings
    render_sidebar()

    # Render main chat interface with business logic functions
    render_main_chat_interface(get_sql_from_llm, execute_sql_query)


if __name__ == "__main__":
    main()
