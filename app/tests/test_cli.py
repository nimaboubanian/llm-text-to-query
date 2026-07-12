from text2query.server.cli import format_result, format_table


def test_format_table_empty_result():
    assert format_table(["name"], []) == "(empty result set)"


def test_format_table_renders_aligned_rows():
    output = format_table(["id", "name"], [[1, "Alice"], [2, "Bob"]])
    lines = output.splitlines()
    assert lines[0].split() == ["id", "name"]
    assert "Alice" in output
    assert "Bob" in output


def test_format_result_success_payload():
    payload = {
        "sql": "SELECT name FROM customers;",
        "columns": ["name"],
        "rows": [["Alice"]],
        "row_count": 1,
        "error": None,
    }
    output = format_result(payload)
    assert "SELECT name FROM customers;" in output
    assert "Alice" in output
    assert "1 row(s)" in output
