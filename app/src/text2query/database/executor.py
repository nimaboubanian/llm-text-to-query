import logging
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 30_000
MAX_RESULT_ROWS = 10_000


@dataclass
class ExecutionResult:
    """Outcome of running a SQL query: either data or an error, never both."""
    data: pd.DataFrame | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None


def execute_sql_query(engine, query: str) -> ExecutionResult:
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}"))
            conn.execute(text("SET TRANSACTION READ ONLY"))
            result = conn.execute(text(query))
            rows = result.fetchmany(MAX_RESULT_ROWS)
            return ExecutionResult(pd.DataFrame(rows, columns=result.keys()), None)
    except Exception as e:
        logger.warning("Query execution failed: %s", e)
        return ExecutionResult(None, str(e))
