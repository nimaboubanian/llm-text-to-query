"""SQL query execution via SQLAlchemy."""

import pandas as pd
from sqlalchemy import text


def execute_sql_query(engine, query: str):
    """Execute SQL query and return DataFrame or error string."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            return pd.DataFrame(result.fetchall(), columns=result.keys())
    except Exception as e:
        return str(e)
