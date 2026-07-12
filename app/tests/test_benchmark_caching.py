"""Tests for fingerprint-keyed benchmark caching (generation resume + answer invalidation)."""
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from text2query.benchmark.fingerprint import read_manifest_fingerprint, write_manifest
from text2query.benchmark.runner import run_llm_generation, execute_generated_queries
from text2query.database.executor import ExecutionResult


def _make_question_file(questions_dir: Path, qid: str, question: str):
    content = f'# Business Question:\n  "{question}"\n'
    (questions_dir / f"{qid}.md").write_text(content)


def test_identical_config_resumes_from_cache(tmp_path):
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    call_count = {"n": 0}

    def mock_streaming(*args, **kwargs):
        call_count["n"] += 1
        yield {"type": "done", "sql": "SELECT name FROM customers;", "full_response": "r", "prompt": "p"}

    with patch("text2query.llm.ollama.OllamaProvider.generate_sql_streaming", side_effect=mock_streaming), \
         patch("text2query.llm.ollama.OllamaProvider.warmup", return_value=True), \
         patch("text2query.benchmark.runner.create_engine_for_database"), \
         patch("text2query.benchmark.runner.get_database_schema_string", return_value="schema"):

        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)
        assert call_count["n"] == 1

        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)
        assert call_count["n"] == 1  # cache hit — no second LLM call

    assert (output_dir / "01.sql").exists()
    assert (output_dir / "manifest.json").exists()


def test_model_change_invalidates_and_regenerates(tmp_path, capsys):
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    call_count = {"n": 0}

    def mock_streaming(*args, **kwargs):
        call_count["n"] += 1
        yield {"type": "done", "sql": "SELECT name FROM customers;", "full_response": "r", "prompt": "p"}

    with patch("text2query.llm.ollama.OllamaProvider.generate_sql_streaming", side_effect=mock_streaming), \
         patch("text2query.llm.ollama.OllamaProvider.warmup", return_value=True), \
         patch("text2query.benchmark.runner.create_engine_for_database"), \
         patch("text2query.benchmark.runner.get_database_schema_string", return_value="schema"):

        run_llm_generation(questions_dir, output_dir, "db://url", "model-a", seeds=None)
        assert call_count["n"] == 1
        capsys.readouterr()

        run_llm_generation(questions_dir, output_dir, "db://url", "model-b", seeds=None)

    assert call_count["n"] == 2  # regenerated, not reused
    assert "config changed" in capsys.readouterr().out
    assert (output_dir / "01.sql").exists()


def test_schema_change_invalidates_and_regenerates(tmp_path, capsys):
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    call_count = {"n": 0}

    def mock_streaming(*args, **kwargs):
        call_count["n"] += 1
        yield {"type": "done", "sql": "SELECT name FROM customers;", "full_response": "r", "prompt": "p"}

    with patch("text2query.llm.ollama.OllamaProvider.generate_sql_streaming", side_effect=mock_streaming), \
         patch("text2query.llm.ollama.OllamaProvider.warmup", return_value=True), \
         patch("text2query.benchmark.runner.create_engine_for_database"), \
         patch("text2query.benchmark.runner.get_database_schema_string", side_effect=["schema-v1", "schema-v2"]):

        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)
        assert call_count["n"] == 1
        capsys.readouterr()

        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)

    assert call_count["n"] == 2
    assert "config changed" in capsys.readouterr().out


def test_temperature_change_invalidates_and_regenerates(tmp_path, capsys, monkeypatch):
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    call_count = {"n": 0}

    def mock_streaming(*args, **kwargs):
        call_count["n"] += 1
        yield {"type": "done", "sql": "SELECT name FROM customers;", "full_response": "r", "prompt": "p"}

    with patch("text2query.llm.ollama.OllamaProvider.generate_sql_streaming", side_effect=mock_streaming), \
         patch("text2query.llm.ollama.OllamaProvider.warmup", return_value=True), \
         patch("text2query.benchmark.runner.create_engine_for_database"), \
         patch("text2query.benchmark.runner.get_database_schema_string", return_value="schema"):

        monkeypatch.setattr("text2query.benchmark.runner.LLM_TEMPERATURE", 0.1)
        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)
        assert call_count["n"] == 1
        capsys.readouterr()

        monkeypatch.setattr("text2query.benchmark.runner.LLM_TEMPERATURE", 0.9)
        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)

    assert call_count["n"] == 2
    assert "config changed" in capsys.readouterr().out


def test_stale_answers_cleared_when_queries_manifest_changes(tmp_path, monkeypatch):
    queries_dir = tmp_path / "queries"
    answers_dir = tmp_path / "answers"
    queries_dir.mkdir()
    (queries_dir / "01.sql").write_text("SELECT 1")
    write_manifest(queries_dir, "fp-old", {"model": "m1"})

    call_count = {"n": 0}

    def fake_execute(engine, sql):
        call_count["n"] += 1
        return ExecutionResult(pd.DataFrame({"x": [1]}), None)

    monkeypatch.setattr("text2query.benchmark.pipeline.create_engine_for_database", lambda url: None)
    monkeypatch.setattr("text2query.benchmark.pipeline.execute_sql_query", fake_execute)

    execute_generated_queries(queries_dir, answers_dir, "db://url", seeds=None)
    assert call_count["n"] == 1
    assert read_manifest_fingerprint(answers_dir) == "fp-old"

    # Same fingerprint on resume — cache hit, no re-execution
    execute_generated_queries(queries_dir, answers_dir, "db://url", seeds=None)
    assert call_count["n"] == 1

    # Queries regenerated with a new fingerprint
    write_manifest(queries_dir, "fp-new", {"model": "m2"})

    execute_generated_queries(queries_dir, answers_dir, "db://url", seeds=None)
    assert call_count["n"] == 2  # stale answer cleared, re-executed
    assert read_manifest_fingerprint(answers_dir) == "fp-new"
