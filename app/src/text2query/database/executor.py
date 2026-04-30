import pandas as pd
from sqlalchemy import text

STATEMENT_TIMEOUT_MS = 30_000
MAX_RESULT_ROWS = 10_000


def execute_sql_query(engine, query: str) -> pd.DataFrame | str:
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}"))
            result = conn.execute(text(query))
            rows = result.fetchmany(MAX_RESULT_ROWS)
            return pd.DataFrame(rows, columns=result.keys())
    except Exception as e:
        return str(e)
