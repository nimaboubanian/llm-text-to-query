"""LLM service for generating SQL/queries from natural language."""

import re

import requests

from core.config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT
from core.database_config import DatabaseType


# Map database types to SQL dialects for prompt generation
DIALECT_MAP = {
    DatabaseType.POSTGRESQL: "PostgreSQL",
    DatabaseType.MYSQL: "MySQL",
    DatabaseType.MARIADB: "MariaDB (MySQL-compatible)",
    DatabaseType.SQLITE: "SQLite",
    DatabaseType.MONGODB: "MongoDB (use MongoDB query syntax, not SQL)",
    DatabaseType.SQLSERVER: "Microsoft SQL Server (T-SQL)",
    DatabaseType.CLICKHOUSE: "ClickHouse SQL",
    DatabaseType.NEO4J: "Neo4j Cypher (graph query language, not SQL)",
}


def get_sql_from_llm(
    user_query: str,
    schema_str: str,
    db_type: DatabaseType = DatabaseType.POSTGRESQL,
) -> tuple[str | None, str | None]:
    """
    Send the prompt to Ollama and return the generated SQL.

    Args:
        user_query: Natural language question from the user
        schema_str: Database schema string for context
        db_type: Type of database to generate query for

    Returns:
        Tuple of (sql_query, error_message). One will be None.
    """
    dialect = DIALECT_MAP.get(db_type, "SQL")
    prompt = _build_prompt(user_query, schema_str, dialect)
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate", json=payload, timeout=OLLAMA_TIMEOUT
        )

        if response.status_code == 404:
            return (
                None,
                f"Model '{OLLAMA_MODEL}' not found. "
                f"Please run: docker exec ollama-model-init ollama pull {OLLAMA_MODEL}",
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


def _build_prompt(user_query: str, schema_str: str, dialect: str) -> str:
    """Build the prompt for the LLM."""
    return (
        f"You are a {dialect} query generator. "
        f"Given the following database schema:\n{schema_str}\n\n"
        f"Generate a query to answer: {user_query}\n\n"
        f"Rules:\n"
        f"- Return ONLY the query, nothing else\n"
        f"- No explanations, no comments, no markdown\n"
        f"- Only use tables and columns from the schema above\n"
        f"- Use {dialect} syntax"
    )


def clean_sql_response(response: str) -> str | None:
    """
    Extract clean SQL from LLM response that may contain markdown or explanations.

    Args:
        response: Raw response from the LLM

    Returns:
        Cleaned SQL query or None if extraction failed
    """
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
