import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from text2query.core.config import DATABASE_URL
from text2query.database.executor import execute_sql_query


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
