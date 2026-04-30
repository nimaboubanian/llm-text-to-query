import pytest
from text2query.llm.service import _clean_sql_response


def test_extracts_sql_from_fenced_block():
    response = "Here's the query:\n```sql\nSELECT id FROM users\n```\nHope that helps."
    assert _clean_sql_response(response) == "SELECT id FROM users"


def test_extracts_sql_from_untagged_fence():
    response = "```\nSELECT count(*) FROM orders\n```"
    assert _clean_sql_response(response) == "SELECT count(*) FROM orders"


def test_extracts_bare_sql_with_semicolon():
    response = "Try this: SELECT name FROM customers WHERE id = 1;"
    result = _clean_sql_response(response)
    assert result is not None
    assert result.startswith("SELECT")
    assert result.endswith(";")


def test_returns_none_for_no_sql():
    assert _clean_sql_response("I don't know how to answer that.") is None


def test_returns_none_for_empty_input():
    assert _clean_sql_response("") is None
    assert _clean_sql_response(None) is None


def test_fenced_block_case_insensitive():
    response = "```SQL\nSELECT 1\n```"
    assert _clean_sql_response(response) == "SELECT 1"


def test_multiline_fenced_sql():
    response = """```sql
SELECT o.id, c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.total > 100
```"""
    result = _clean_sql_response(response)
    assert "SELECT o.id" in result
    assert "WHERE o.total > 100" in result


def test_rejects_bare_insert():
    assert _clean_sql_response("INSERT INTO users VALUES (1, 'alice');") is None


def test_rejects_bare_update():
    assert _clean_sql_response("UPDATE users SET name = 'bob' WHERE id = 1;") is None


def test_rejects_bare_delete():
    assert _clean_sql_response("DELETE FROM users WHERE id = 1;") is None


def test_rejects_multi_statement_in_fence():
    response = "```sql\nSELECT 1; DROP TABLE users;\n```"
    assert _clean_sql_response(response) is None


def test_bare_multi_statement_extracts_only_first():
    """The regex captures only the first SELECT...;, ignoring trailing statements."""
    response = "SELECT 1; DROP TABLE users;"
    assert _clean_sql_response(response) == "SELECT 1;"


def test_allows_single_statement_with_trailing_semicolon():
    response = "```sql\nSELECT id FROM users;\n```"
    assert _clean_sql_response(response) == "SELECT id FROM users;"
