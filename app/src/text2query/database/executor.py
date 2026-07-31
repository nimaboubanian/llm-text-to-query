import logging
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 30_000
MAX_RESULT_ROWS = 100_000  # ponytail: flat cap; per-caller limits if SF>10 ground truth ever needed


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
            if len(rows) == MAX_RESULT_ROWS and result.fetchone() is not None:
                logger.warning("Result truncated at %d rows — scores against this result are unreliable", MAX_RESULT_ROWS)
            return ExecutionResult(pd.DataFrame(rows, columns=result.keys()), None)
    except Exception as e:
        logger.warning("Query execution failed: %s", e)
        return ExecutionResult(None, str(e))


def explain_error(engine, sql: str) -> str | None:
    """Cheap validity probe: EXPLAIN surfaces syntax/schema errors without running the query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"EXPLAIN {sql}"))
        return None
    except Exception as e:
        # str(e) on a SQLAlchemy DBAPIError dumps the executed statement verbatim —
        # including our "EXPLAIN " wrapper — back into the message. That message is
        # fed into the retry prompt (ollama.py) and shown to the model as if it were
        # its own previous query, which it then sometimes echoes back literally.
        # .orig is the bare driver exception with just the real error text.
        return str(getattr(e, "orig", e))
