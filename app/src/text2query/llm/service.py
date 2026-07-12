import re

import sqlglot
from sqlglot import exp


def _build_prompt(user_query: str, schema_str: str) -> str:
    from text2query.llm.prompts import DEFAULT_SQL_GENERATION_TEMPLATE
    return DEFAULT_SQL_GENERATION_TEMPLATE.format(
        schema=schema_str,
        query=user_query,
    )


def _is_single_statement(sql: str) -> bool:
    """Reject multi-statement SQL to prevent piggyback attacks."""
    stripped = sql.strip().rstrip(";")
    return ";" not in stripped


def _is_select_only(sql: str) -> bool:
    """Accept only SELECT statements (including CTEs and set operations); reject DDL/DML."""
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        parsed = None

    if parsed is not None:
        return isinstance(parsed, (exp.Select, exp.Union))

    # sqlglot couldn't parse it (e.g. dialect quirks) — fall back to a conservative
    # keyword-prefix check so valid SELECTs aren't unfairly rejected.
    return bool(re.match(r"(?i)^\s*(SELECT|WITH)\b", sql))


def _is_safe_sql(sql: str) -> bool:
    return _is_single_statement(sql) and _is_select_only(sql)


def _clean_sql_response(response: str) -> str | None:
    if not response:
        return None

    match = re.search(r"```(?:sql)?\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
    if match:
        sql = match.group(1).strip()
        return sql if _is_safe_sql(sql) else None

    match = re.search(r"(SELECT|WITH)\s+.*?;", response, re.DOTALL | re.IGNORECASE)
    if match:
        sql = match.group(0).strip()
        return sql if _is_safe_sql(sql) else None

    return None
