import json
import threading
import urllib.request
from datetime import date
from decimal import Decimal
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock

import pandas as pd
import pytest

from text2query.database.executor import ExecutionResult
from text2query.llm.ollama import GenerationResult
from text2query.server.main import AppContext, RequestError, _make_handler, handle_query, parse_question


def test_parse_question_rejects_invalid_json():
    with pytest.raises(RequestError) as exc:
        parse_question(b"not json")
    assert exc.value.status == 400


def test_parse_question_rejects_missing_field():
    with pytest.raises(RequestError) as exc:
        parse_question(json.dumps({}).encode())
    assert exc.value.status == 400


def test_parse_question_rejects_empty_string():
    with pytest.raises(RequestError) as exc:
        parse_question(json.dumps({"question": "   "}).encode())
    assert exc.value.status == 400


def test_parse_question_rejects_oversized_input():
    with pytest.raises(RequestError) as exc:
        parse_question(json.dumps({"question": "x" * 2001}).encode())
    assert exc.value.status == 400


def test_parse_question_strips_and_returns_valid_input():
    assert parse_question(json.dumps({"question": "  how many rows?  "}).encode()) == "how many rows?"


def test_handle_query_generation_error_maps_to_422():
    llm = MagicMock()
    llm.generate_sql_with_retry.return_value = GenerationResult(sql=None, error="Model 'x' not found.")

    with pytest.raises(RequestError) as exc:
        handle_query(llm, engine=MagicMock(), schema="s", model="m", question="q")

    assert exc.value.status == 422
    assert "not found" in exc.value.message


def test_handle_query_no_sql_extracted_maps_to_422():
    llm = MagicMock()
    llm.generate_sql_with_retry.return_value = GenerationResult(sql=None, raw_response="I can't help with that")

    with pytest.raises(RequestError) as exc:
        handle_query(llm, engine=MagicMock(), schema="s", model="m", question="q")

    assert exc.value.status == 422


def test_handle_query_database_error_maps_to_502(monkeypatch):
    llm = MagicMock()
    llm.generate_sql_with_retry.return_value = GenerationResult(sql="SELECT 1;")

    monkeypatch.setattr(
        "text2query.server.main.execute_sql_query",
        lambda engine, sql: ExecutionResult(None, "relation does not exist"),
    )

    with pytest.raises(RequestError) as exc:
        handle_query(llm, engine=MagicMock(), schema="s", model="m", question="q")

    assert exc.value.status == 502
    assert "does not exist" in exc.value.message


def test_handle_query_success_returns_response_payload(monkeypatch):
    llm = MagicMock()
    llm.generate_sql_with_retry.return_value = GenerationResult(sql="SELECT name FROM customers;")

    df = pd.DataFrame({"name": ["Alice", "Bob"]})
    monkeypatch.setattr(
        "text2query.server.main.execute_sql_query",
        lambda engine, sql: ExecutionResult(df, None),
    )

    payload = handle_query(llm, engine=MagicMock(), schema="s", model="m", question="q")

    assert payload["sql"] == "SELECT name FROM customers;"
    assert payload["columns"] == ["name"]
    assert payload["rows"] == [["Alice"], ["Bob"]]
    assert payload["row_count"] == 2
    assert payload["error"] is None


def test_handle_query_serializes_decimal_date_and_nan(monkeypatch):
    """Postgres NUMERIC/DATE/NULL values must not crash json.dumps (regression)."""
    llm = MagicMock()
    llm.generate_sql_with_retry.return_value = GenerationResult(sql="SELECT * FROM orders;")

    df = pd.DataFrame({
        "name": ["Alice", "Bob"],
        "spent": [Decimal("19.99"), None],   # NUMERIC column with a NULL
        "joined": [date(2024, 1, 5), date(2024, 2, 1)],
        "score": [1.5, float("nan")],        # numeric NULL surfaces as NaN
    })
    monkeypatch.setattr(
        "text2query.server.main.execute_sql_query",
        lambda engine, sql: ExecutionResult(df, None),
    )

    payload = handle_query(llm, engine=MagicMock(), schema="s", model="m", question="q")

    serialized = json.dumps(payload)          # must not raise
    assert "NaN" not in serialized            # NaN is invalid JSON for non-Python clients
    assert payload["rows"][0] == ["Alice", 19.99, "2024-01-05", 1.5]
    assert payload["rows"][1] == ["Bob", None, "2024-02-01", None]


def _serve(ctx):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(ctx))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_handler_serves_health_and_query_end_to_end(monkeypatch):
    """Exercise real HTTP routing through the Handler, not just the pure helpers."""
    llm = MagicMock()
    llm.generate_sql_with_retry.return_value = GenerationResult(sql="SELECT name, price FROM products;")
    df = pd.DataFrame({"name": ["Widget"], "price": [Decimal("9.99")]})
    monkeypatch.setattr(
        "text2query.server.main.execute_sql_query",
        lambda engine, sql: ExecutionResult(df, None),
    )

    ctx = AppContext.__new__(AppContext)
    ctx.engine = None
    ctx.schema = "schema"
    ctx.llm = llm

    server, port = _serve(ctx)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            assert resp.status == 200
            assert json.loads(resp.read()) == {"status": "ok"}

        body = json.dumps({"question": "list products"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/query", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read())

        assert payload["columns"] == ["name", "price"]
        assert payload["rows"] == [["Widget", 9.99]]
        assert payload["row_count"] == 1
    finally:
        server.shutdown()
