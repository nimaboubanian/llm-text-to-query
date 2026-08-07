"""Tests for fingerprint-keyed benchmark caching (generation resume + answer invalidation)."""
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from backend.benchmark.fingerprint import read_manifest_fingerprint, write_manifest
from backend.benchmark.runner import run_llm_generation, execute_generated_queries
from backend.database.executor import ExecutionResult
from backend.llm.ollama import GenerationResult


def _make_question_file(questions_dir: Path, qid: str, question: str):
    content = f'# Business Question:\n  "{question}"\n'
    (questions_dir / f"{qid}.md").write_text(content)


def test_identical_config_resumes_from_cache(tmp_path):
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    call_count = {"n": 0}

    def mock_generate(*args, **kwargs):
        call_count["n"] += 1
        return GenerationResult(sql="SELECT name FROM customers;", raw_response="r", prompt="p")

    with patch("backend.llm.ollama.generate_sql", side_effect=mock_generate), \
         patch("backend.llm.ollama.warmup", return_value=True), \
         patch("backend.benchmark.runner.create_engine_for_database"), \
         patch("backend.benchmark.runner.render_schema", return_value="schema"):

        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)
        assert call_count["n"] == 1

        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)
        assert call_count["n"] == 1  # cache hit — no second LLM call

    assert (output_dir / "seed_1" / "01.sql").exists()
    assert (output_dir / "seed_1" / "manifest.json").exists()


def test_model_change_invalidates_and_regenerates(tmp_path, capsys):
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    call_count = {"n": 0}

    def mock_generate(*args, **kwargs):
        call_count["n"] += 1
        return GenerationResult(sql="SELECT name FROM customers;", raw_response="r", prompt="p")

    with patch("backend.llm.ollama.generate_sql", side_effect=mock_generate), \
         patch("backend.llm.ollama.warmup", return_value=True), \
         patch("backend.benchmark.runner.create_engine_for_database"), \
         patch("backend.benchmark.runner.render_schema", return_value="schema"):

        run_llm_generation(questions_dir, output_dir, "db://url", "model-a", seeds=None)
        assert call_count["n"] == 1
        capsys.readouterr()

        run_llm_generation(questions_dir, output_dir, "db://url", "model-b", seeds=None)

    assert call_count["n"] == 2  # regenerated, not reused
    assert "config changed" in capsys.readouterr().out
    assert (output_dir / "seed_1" / "01.sql").exists()


def test_schema_change_invalidates_and_regenerates(tmp_path, capsys):
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")

    call_count = {"n": 0}

    def mock_generate(*args, **kwargs):
        call_count["n"] += 1
        return GenerationResult(sql="SELECT name FROM customers;", raw_response="r", prompt="p")

    with patch("backend.llm.ollama.generate_sql", side_effect=mock_generate), \
         patch("backend.llm.ollama.warmup", return_value=True), \
         patch("backend.benchmark.runner.create_engine_for_database"), \
         patch("backend.benchmark.runner.render_schema", side_effect=["schema-v1", "schema-v2"]):

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

    def mock_generate(*args, **kwargs):
        call_count["n"] += 1
        return GenerationResult(sql="SELECT name FROM customers;", raw_response="r", prompt="p")

    with patch("backend.llm.ollama.generate_sql", side_effect=mock_generate), \
         patch("backend.llm.ollama.warmup", return_value=True), \
         patch("backend.benchmark.runner.create_engine_for_database"), \
         patch("backend.benchmark.runner.render_schema", return_value="schema"):

        monkeypatch.setattr("backend.benchmark.runner.LLM_TEMPERATURE", 0.1)
        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)
        assert call_count["n"] == 1
        capsys.readouterr()

        monkeypatch.setattr("backend.benchmark.runner.LLM_TEMPERATURE", 0.9)
        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)

    assert call_count["n"] == 2
    assert "config changed" in capsys.readouterr().out


def test_query_ids_filter_does_not_invalidate_cache(tmp_path, capsys):
    """Resuming with a query_ids subset must not change the fingerprint (Finding 1):
    the questions digest has to be computed over the full question set, not the
    filtered one, or a --query-ids re-run wipes the whole generation cache."""
    questions_dir = tmp_path / "questions"
    output_dir = tmp_path / "output"
    questions_dir.mkdir()
    _make_question_file(questions_dir, "01", "What are the customer names?")
    _make_question_file(questions_dir, "02", "How many orders are there?")

    call_count = {"n": 0}

    def mock_generate(*args, **kwargs):
        call_count["n"] += 1
        return GenerationResult(sql="SELECT name FROM customers;", raw_response="r", prompt="p")

    with patch("backend.llm.ollama.generate_sql", side_effect=mock_generate), \
         patch("backend.llm.ollama.warmup", return_value=True), \
         patch("backend.benchmark.runner.create_engine_for_database"), \
         patch("backend.benchmark.runner.render_schema", return_value="schema"):

        run_llm_generation(questions_dir, output_dir, "db://url", "test-model", seeds=None)
        assert call_count["n"] == 2
        capsys.readouterr()

        # Re-run filtered to just one query id, as if resuming after an interruption.
        run_llm_generation(
            questions_dir, output_dir, "db://url", "test-model", seeds=None, query_ids=["02"],
        )

    assert call_count["n"] == 2  # both still cached — no stale-cache wipe from filtering
    assert "config changed" not in capsys.readouterr().out
    assert (output_dir / "seed_1" / "01.sql").exists()
    assert (output_dir / "seed_1" / "02.sql").exists()


def test_stale_answers_cleared_when_queries_manifest_changes(tmp_path, monkeypatch):
    queries_dir = tmp_path / "queries"
    answers_dir = tmp_path / "answers"
    seed_queries_dir = queries_dir / "seed_1"
    seed_queries_dir.mkdir(parents=True)
    (seed_queries_dir / "01.sql").write_text("SELECT 1")
    write_manifest(seed_queries_dir, "fp-old", {"model": "m1"})

    call_count = {"n": 0}

    def fake_execute(engine, sql):
        call_count["n"] += 1
        return ExecutionResult(pd.DataFrame({"x": [1]}), None)

    monkeypatch.setattr("backend.benchmark.pipeline.create_engine_for_database", lambda url: None)
    monkeypatch.setattr("backend.benchmark.pipeline.execute_sql_query", fake_execute)

    execute_generated_queries(queries_dir, answers_dir, "db://url", seeds=None)
    assert call_count["n"] == 1
    assert read_manifest_fingerprint(answers_dir / "seed_1") == "fp-old"

    # Same fingerprint on resume — cache hit, no re-execution
    execute_generated_queries(queries_dir, answers_dir, "db://url", seeds=None)
    assert call_count["n"] == 1

    # Queries regenerated with a new fingerprint
    write_manifest(seed_queries_dir, "fp-new", {"model": "m2"})

    execute_generated_queries(queries_dir, answers_dir, "db://url", seeds=None)
    assert call_count["n"] == 2  # stale answer cleared, re-executed
    assert read_manifest_fingerprint(answers_dir / "seed_1") == "fp-new"


def test_generate_answers_regenerates_when_query_content_changes(tmp_path, monkeypatch):
    queries = tmp_path / "queries"; queries.mkdir()
    answers = tmp_path / "answers"; answers.mkdir()
    (queries / "01.sql").write_text("SELECT 1;")
    (answers / "01.csv").write_text("a\n1\n")

    calls = []
    monkeypatch.setattr(
        "backend.benchmark.pipeline.execute_queries_to_csv",
        lambda files, out, db, **kw: calls.append([f.stem for f in files]) or [
            {"query_id": f.stem, "status": "success", "rows": 1} for f in files],
    )

    from backend.benchmark.pipeline import generate_answers
    generate_answers(queries, answers, "sqlite://", scale_factor=1)   # first run: manifest written
    generate_answers(queries, answers, "sqlite://", scale_factor=1)   # unchanged: no regeneration
    (queries / "01.sql").write_text("SELECT 2;")                       # content edit, same filename
    (answers / "01.csv").write_text("a\n1\n")                          # stale CSV still present
    generate_answers(queries, answers, "sqlite://", scale_factor=1)    # must regenerate
    assert calls[-1] == ["01"]
    n_after_content_change = len(calls)
    assert n_after_content_change >= 2

    (answers / "01.csv").write_text("a\n1\n")                          # stale CSV again
    generate_answers(queries, answers, "sqlite://", scale_factor=10)   # SF change must regenerate
    assert len(calls) == n_after_content_change + 1 and calls[-1] == ["01"]


def test_generate_answers_raises_on_reference_failure(tmp_path, monkeypatch):
    queries = tmp_path / "queries"; queries.mkdir()
    answers = tmp_path / "answers"
    (queries / "01.sql").write_text("SELECT broken;")

    monkeypatch.setattr(
        "backend.benchmark.pipeline.execute_queries_to_csv",
        lambda files, out, db, **kw: [{"query_id": "01", "status": "error", "error": "boom"}],
    )

    from backend.benchmark.pipeline import generate_answers
    with pytest.raises(RuntimeError, match="01"):
        generate_answers(queries, answers, "sqlite://", scale_factor=1)
