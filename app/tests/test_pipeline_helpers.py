from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from text2query.benchmark.data_loader import TPCH_TABLES
from text2query.benchmark.pipeline import (
    check_database_readiness,
    ensure_database_exists,
    execute_queries_to_csv,
    read_business_question,
)
from text2query.database.executor import ExecutionResult


def _tpch_sqlite_engine(row_counts: dict[str, int], default_rows: int = 1):
    """In-memory SQLite engine with all 8 TPCH-named tables, each pre-populated.

    `row_counts` overrides `default_rows` per table (used to simulate a
    half-loaded or wrong-scale-factor database).
    """
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as conn:
        for table in TPCH_TABLES:
            conn.execute(text(f"CREATE TABLE {table} (id INTEGER)"))
            rows = [{"i": i} for i in range(row_counts.get(table, default_rows))]
            if rows:
                conn.execute(text(f"INSERT INTO {table} (id) VALUES (:i)"), rows)
    return engine


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


class TestCheckDatabaseReadiness:
    def _patch(self, monkeypatch, engine):
        monkeypatch.setattr(
            "text2query.benchmark.pipeline.create_engine_for_database", lambda url: engine
        )

    def test_ready_when_fixed_tables_have_correct_counts(self, monkeypatch):
        engine = _tpch_sqlite_engine({"nation": 25, "region": 5, "supplier": 10_000})
        self._patch(monkeypatch, engine)

        assert check_database_readiness("sqlite://", scale_factor=1) is True

    def test_rejects_wrong_fixed_table_counts(self, monkeypatch):
        # all 8 tables exist with 1 row each — passes the old "non-empty" check,
        # but nation/region/supplier don't match their expected fixed counts.
        engine = _tpch_sqlite_engine({}, default_rows=1)
        self._patch(monkeypatch, engine)

        assert check_database_readiness("sqlite://", scale_factor=1) is False

    def test_supplier_count_scales_with_scale_factor(self, monkeypatch):
        engine = _tpch_sqlite_engine({"nation": 25, "region": 5, "supplier": 20_000})
        self._patch(monkeypatch, engine)

        assert check_database_readiness("sqlite://", scale_factor=2) is True
        assert check_database_readiness("sqlite://", scale_factor=1) is False


class TestReadBusinessQuestion:
    def test_extracts_full_prose_with_internal_quoted_term(self, tmp_path):
        qfile = tmp_path / "03.md"
        qfile.write_text(
            '# Business Question:\n'
            '"Among all orders placed by customers in the "Building" market segment, '
            'which 10 orders represent the greatest potential revenue?"\n'
        )

        result = read_business_question(qfile)

        assert result == (
            'Among all orders placed by customers in the "Building" market segment, '
            'which 10 orders represent the greatest potential revenue?'
        )

    def test_extracts_full_prose_with_no_internal_quotes(self, tmp_path):
        qfile = tmp_path / "06.md"
        qfile.write_text(
            '# Business Question:\n'
            '"If we had eliminated all discounts, how much revenue would we have collected?"\n'
        )

        result = read_business_question(qfile)

        assert result == "If we had eliminated all discounts, how much revenue would we have collected?"

    def test_missing_file_returns_none(self, tmp_path):
        qfile = tmp_path / "does-not-exist.md"

        assert read_business_question(qfile) is None


class TestEnsureDatabaseExists:
    """The benchmark provisions its own database on a pre-existing pg_data volume."""

    class _Result:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _Conn:
        def __init__(self, exists: bool, executed: list):
            self._exists = exists
            self.executed = executed

        def execute(self, stmt, params=None):
            self.executed.append(str(stmt))
            return TestEnsureDatabaseExists._Result((1,) if self._exists else None)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _Engine:
        def __init__(self, conn):
            self._conn = conn

        def connect(self):
            return self._conn

        def dispose(self):
            pass

    def _patch(self, monkeypatch, exists: bool, seen: dict | None = None):
        executed = []
        conn = self._Conn(exists, executed)

        def _fake_create_engine(url, **kwargs):
            if seen is not None:
                seen["database"] = url.database
                seen["isolation_level"] = kwargs.get("isolation_level")
            return self._Engine(conn)

        monkeypatch.setattr(
            "text2query.benchmark.pipeline.create_engine", _fake_create_engine
        )
        return executed

    def test_creates_the_database_when_missing(self, monkeypatch):
        executed = self._patch(monkeypatch, exists=False)
        created = ensure_database_exists("postgresql://user:password@postgres:5432/tpch")
        assert created is True
        assert any('CREATE DATABASE "tpch"' in stmt for stmt in executed)

    def test_is_a_noop_when_the_database_is_present(self, monkeypatch):
        executed = self._patch(monkeypatch, exists=True)
        created = ensure_database_exists("postgresql://user:password@postgres:5432/tpch")
        assert created is False
        assert not any("CREATE DATABASE" in stmt for stmt in executed)

    def test_connects_to_the_maintenance_database_in_autocommit(self, monkeypatch):
        # CREATE DATABASE cannot run inside a transaction block, and it cannot run
        # while connected to the database being created.
        seen = {}
        self._patch(monkeypatch, exists=False, seen=seen)
        ensure_database_exists("postgresql://user:password@postgres:5432/tpch")
        assert seen["database"] == "postgres"
        assert seen["isolation_level"] == "AUTOCOMMIT"
