from text2query.benchmark.pipeline import execute_queries_to_csv
from text2query.database.executor import ExecutionResult


class TestExecuteQueriesToCsv:
    def _patch(self, monkeypatch, result: ExecutionResult):
        monkeypatch.setattr(
            "text2query.benchmark.pipeline.create_engine_for_database", lambda url: None
        )
        monkeypatch.setattr(
            "text2query.benchmark.pipeline.execute_sql_query", lambda engine, sql: result
        )

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

    def test_invokes_item_callbacks_with_outcome(self, tmp_path, monkeypatch):
        import pandas as pd
        self._patch(monkeypatch, ExecutionResult(pd.DataFrame({"a": [1, 2]}), None))
        query_file = tmp_path / "01.sql"
        query_file.write_text("SELECT 1")
        output_dir = tmp_path / "answers"

        starts = []
        outcomes = []

        execute_queries_to_csv(
            [query_file], output_dir, "postgresql://fake",
            on_item_start=lambda i, total, label: starts.append((i, total, label)),
            on_item_done=lambda outcome: outcomes.append(outcome),
        )

        assert starts == [(1, 1, "Q01")]
        assert outcomes == [" ✓ (2 rows)"]
