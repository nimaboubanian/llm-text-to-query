import json
from unittest.mock import MagicMock

import pandas as pd
import pytest

from text2query.database.executor import ExecutionResult
from text2query.llm.provider import GenerationResult
from text2query.server.main import RequestError, handle_query, parse_question


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
    llm.generate_sql.return_value = GenerationResult(sql=None, error="Model 'x' not found.")

    with pytest.raises(RequestError) as exc:
        handle_query(llm, engine=MagicMock(), schema="s", model="m", question="q")

    assert exc.value.status == 422
    assert "not found" in exc.value.message


def test_handle_query_no_sql_extracted_maps_to_422():
    llm = MagicMock()
    llm.generate_sql.return_value = GenerationResult(sql=None, raw_response="I can't help with that")

    with pytest.raises(RequestError) as exc:
        handle_query(llm, engine=MagicMock(), schema="s", model="m", question="q")

    assert exc.value.status == 422


def test_handle_query_database_error_maps_to_502(monkeypatch):
    llm = MagicMock()
    llm.generate_sql.return_value = GenerationResult(sql="SELECT 1;")

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
    llm.generate_sql.return_value = GenerationResult(sql="SELECT name FROM customers;")

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
