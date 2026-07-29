from text2query.llm.ollama import _clean_sql_response


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


def test_rejects_drop_in_fence():
    response = "```sql\nDROP TABLE users\n```"
    assert _clean_sql_response(response) is None


def test_rejects_truncate_in_fence():
    response = "```sql\nTRUNCATE TABLE users\n```"
    assert _clean_sql_response(response) is None


def test_rejects_alter_in_fence():
    response = "```sql\nALTER TABLE users ADD COLUMN x INT\n```"
    assert _clean_sql_response(response) is None


def test_allows_cte_select_in_fence():
    response = (
        "```sql\nWITH recent AS (SELECT id FROM orders) "
        "SELECT * FROM recent\n```"
    )
    result = _clean_sql_response(response)
    assert result is not None
    assert result.upper().startswith("WITH")


def test_allows_union_select_in_fence():
    response = "```sql\nSELECT id FROM a UNION SELECT id FROM b\n```"
    result = _clean_sql_response(response)
    assert result is not None


def test_allows_unparsable_select_prefixed_fallback():
    """sqlglot can't parse this malformed fragment, but the SELECT prefix keeps it safe."""
    response = "```sql\nSELECT * FROM t WHERE (((\n```"
    result = _clean_sql_response(response)
    assert result is not None
    assert result.upper().startswith("SELECT")
