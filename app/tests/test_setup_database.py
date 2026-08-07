from pathlib import Path

import pytest

from backend.benchmark.pipeline import build_indexes, load_data, load_schema


class _FakeConn:
    def __init__(self, executed):
        self._executed = executed

    def execute(self, stmt):
        self._executed.append(str(stmt))


class _FakeTxn:
    def __init__(self, executed):
        self._executed = executed

    def __enter__(self):
        return _FakeConn(self._executed)

    def __exit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self, executed):
        self._executed = executed

    def begin(self):
        return _FakeTxn(self._executed)


def test_load_schema_executes_each_statement(tmp_path, monkeypatch):
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE a (id int);\nCREATE TABLE b (id int);")
    executed = []
    monkeypatch.setattr(
        "backend.benchmark.pipeline.create_engine_for_database",
        lambda url: _FakeEngine(executed),
    )

    load_schema(schema_file, "postgresql://fake")

    # First statement terminates other backends, then the two CREATE TABLEs
    assert len(executed) == 3
    assert "CREATE TABLE a" in executed[1]
    assert "CREATE TABLE b" in executed[2]


def test_load_schema_wraps_failures(tmp_path, monkeypatch):
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE a (id int);")

    class FailingEngine:
        def begin(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "backend.benchmark.pipeline.create_engine_for_database", lambda url: FailingEngine()
    )

    with pytest.raises(RuntimeError, match="Failed to load schema"):
        load_schema(schema_file, "postgresql://fake")


def test_load_data_wraps_missing_files(tmp_path, monkeypatch):
    def fake_load(data_dir, db_url):
        raise FileNotFoundError("Missing .tbl files: region")

    monkeypatch.setattr("backend.benchmark.pipeline.load_tpch_data", fake_load)

    with pytest.raises(RuntimeError, match="Failed to load data"):
        load_data(tmp_path, "postgresql://fake")


def test_load_data_returns_counts(monkeypatch):
    monkeypatch.setattr(
        "backend.benchmark.pipeline.load_tpch_data",
        lambda data_dir, db_url: {"region": 5, "nation": 25},
    )

    counts = load_data(Path("unused"), "postgresql://fake")

    assert counts == {"region": 5, "nation": 25}


def test_build_indexes_returns_false_when_no_indexes_file(tmp_path):
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE a (id int);")

    assert build_indexes(schema_file, "postgresql://fake") is False


def test_build_indexes_executes_statements(tmp_path, monkeypatch):
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE a (id int);")
    (tmp_path / "indexes.sql").write_text("CREATE INDEX idx_a ON a (id);")
    executed = []
    monkeypatch.setattr(
        "backend.benchmark.pipeline.create_engine_for_database",
        lambda url: _FakeEngine(executed),
    )

    built = build_indexes(schema_file, "postgresql://fake")

    assert built is True
    assert len(executed) == 1
    assert "CREATE INDEX idx_a" in executed[0]
