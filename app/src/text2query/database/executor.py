import pandas as pd
from sqlalchemy import text


def execute_sql_query(engine, query: str):
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            return pd.DataFrame(result.fetchall(), columns=result.keys())
    except Exception as e:
        return str(e)
