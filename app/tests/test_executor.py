import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from text2query.core.config import DATABASE_URL
from text2query.database.executor import execute_sql_query
import text2query.database.executor as ex


def _live_engine():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip(f"PostgreSQL not reachable at {DATABASE_URL} — run inside the app container or set DATABASE_URL")
    return engine


@pytest.mark.integration
def test_select_succeeds_against_live_database():
    engine = _live_engine()
    result = execute_sql_query(engine, "SELECT 1 AS x")
    assert result.ok
    assert result.data.iloc[0]["x"] == 1


@pytest.mark.integration
def test_write_statement_rejected_by_read_only_transaction():
    engine = _live_engine()
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS _readonly_probe (id INT)"
        ))
        conn.execute(text("DELETE FROM _readonly_probe"))
        conn.execute(text("INSERT INTO _readonly_probe VALUES (1)"))

    result = execute_sql_query(engine, "DELETE FROM _readonly_probe")

    assert not result.ok
    assert "read-only transaction" in result.error.lower()

    with engine.begin() as conn:
        count = conn.execute(text("SELECT count(*) FROM _readonly_probe")).scalar()
        conn.execute(text("DROP TABLE _readonly_probe"))
    assert count == 1


@pytest.mark.integration
def test_result_at_cap_logs_truncation_warning(caplog):
    engine = _live_engine()
    original = ex.MAX_RESULT_ROWS
    ex.MAX_RESULT_ROWS = 3
    try:
        with caplog.at_level("WARNING"):
            result = ex.execute_sql_query(engine, "SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4")
        assert result.ok
        assert len(result.data) == 3
        assert any("truncated" in r.message.lower() for r in caplog.records)
    finally:
        ex.MAX_RESULT_ROWS = original


@pytest.mark.integration
def test_explain_error_message_excludes_wrapper_and_sql_dump():
    engine = _live_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS _explain_probe (id INT)"))

    # Duplicate alias "a" — same failure shape as the qwen2.5-coder Q07 incident.
    sql = "SELECT a.id FROM _explain_probe a JOIN _explain_probe a ON a.id = a.id"
    error = ex.explain_error(engine, sql)

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE _explain_probe"))

    assert error is not None
    assert "specified more than once" in error.lower()
    assert "EXPLAIN" not in error
    assert "[SQL:" not in error


@pytest.mark.integration
def test_explain_error_strips_explain_from_postgres_line_annotation():
    engine = _live_engine()
    # Syntax error: missing table name in FROM clause.
    # Postgres will report this as "LINE 1: EXPLAIN SELECT * FROM" → error.
    # The fix should strip the "EXPLAIN " so the error just reads "LINE 1: SELECT * FROM".
    sql = "SELECT * FROM"
    error = ex.explain_error(engine, sql)

    assert error is not None
    assert "EXPLAIN" not in error
    assert "syntax error" in error.lower()
