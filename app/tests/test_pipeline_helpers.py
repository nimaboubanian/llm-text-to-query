from pathlib import Path

import pandas as pd
import pytest

from text2query.benchmark.pipeline import _parse_schema_sql, execute_queries_to_csv
from text2query.database.executor import ExecutionResult


class TestParseSchemaSQL:
    def test_splits_statements(self, tmp_path):
        schema = tmp_path / "schema.sql"
        schema.write_text("CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);")
        stmts = _parse_schema_sql(schema)
        assert len(stmts) == 2
        assert stmts[0].startswith("CREATE TABLE a")

    def test_strips_comments(self, tmp_path):
        schema = tmp_path / "schema.sql"
        schema.write_text("-- header comment\nCREATE TABLE t (x INT);")
        stmts = _parse_schema_sql(schema)
        assert len(stmts) == 1
        assert "--" not in stmts[0]

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            _parse_schema_sql(Path("/no/such/file.sql"))

    def test_skips_blank_statements(self, tmp_path):
        schema = tmp_path / "schema.sql"
        schema.write_text("CREATE TABLE x (id INT);\n\n;\n\n")
        stmts = _parse_schema_sql(schema)
        assert len(stmts) == 1


class TestExecuteQueriesToCsv:
    def _patch(self, monkeypatch, result: ExecutionResult):
        monkeypatch.setattr(
            "text2query.benchmark.pipeline.create_engine_for_database", lambda url: None
        )
        monkeypatch.setattr(
            "text2query.benchmark.pipeline.execute_sql_query", lambda engine, sql: result
        )

    def test_writes_csv_on_success(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, ExecutionResult(pd.DataFrame({"x": [1]}), None))
        query_file = tmp_path / "01.sql"
        query_file.write_text("SELECT 1")
        output_dir = tmp_path / "answers"

        results = execute_queries_to_csv([query_file], output_dir, "postgresql://fake")

        assert results[0]["status"] == "success"
        assert (output_dir / "01.csv").exists()
        assert not (output_dir / "01.error").exists()

    def test_writes_error_file_on_failure_when_enabled(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, ExecutionResult(None, "boom"))
        query_file = tmp_path / "01.sql"
        query_file.write_text("SELECT 1")
        output_dir = tmp_path / "answers"

        results = execute_queries_to_csv(
            [query_file], output_dir, "postgresql://fake", write_error_file=True
        )

        assert results[0]["status"] == "error"
        assert not (output_dir / "01.csv").exists()
        assert (output_dir / "01.error").read_text() == "boom"

    def test_no_error_file_when_disabled(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, ExecutionResult(None, "boom"))
        query_file = tmp_path / "01.sql"
        query_file.write_text("SELECT 1")
        output_dir = tmp_path / "answers"

        results = execute_queries_to_csv(
            [query_file], output_dir, "postgresql://fake", write_error_file=False
        )

        assert results[0]["status"] == "error"
        assert not (output_dir / "01.error").exists()


