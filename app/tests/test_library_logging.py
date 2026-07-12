"""Tests that swallowed exceptions in library modules emit log records instead of vanishing."""
import logging

import requests
from sqlalchemy import create_engine

from text2query.database.executor import execute_sql_query
from text2query.benchmark.similarity import _ast_similarity
from text2query.benchmark.validation import check_database_ready
from text2query.llm.ollama import OllamaProvider


def test_execute_sql_query_logs_on_failure(caplog):
    engine = create_engine("sqlite:///:memory:")

    with caplog.at_level(logging.WARNING, logger="text2query.database.executor"):
        result = execute_sql_query(engine, "SELECT 1")

    assert not result.ok
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_ast_similarity_logs_on_malformed_sql(caplog):
    with caplog.at_level(logging.DEBUG, logger="text2query.benchmark.similarity"):
        result = _ast_similarity("SELECT * FROM (((", "SELECT 1")

    assert result is None
    assert any(r.levelno >= logging.DEBUG for r in caplog.records)


def test_check_database_ready_logs_on_failure(caplog, monkeypatch):
    monkeypatch.setattr(
        "text2query.database.schema.create_engine_for_database", lambda url: object()
    )

    def _raise(engine):
        raise RuntimeError("boom")

    monkeypatch.setattr("text2query.benchmark.validation.inspect", _raise)

    with caplog.at_level(logging.WARNING, logger="text2query.benchmark.validation"):
        result = check_database_ready("postgresql://fake")

    assert result is False
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_ollama_list_models_logs_on_request_failure(caplog, monkeypatch):
    def _raise(*args, **kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr("requests.get", _raise)

    with caplog.at_level(logging.WARNING, logger="text2query.llm.ollama"):
        result = OllamaProvider(base_url="http://nowhere:11434").list_models()

    assert result == []
    assert any(r.levelno >= logging.WARNING for r in caplog.records)
