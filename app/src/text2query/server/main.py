import json
import logging
import math
from datetime import date, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pandas as pd

from text2query.core.config import DATABASE_URL, DEFAULT_MODEL, LOG_LEVEL, SERVER_PORT
from text2query.core.flags import GenerationFlags
from text2query.database.executor import execute_sql_query
from text2query.database.schema import create_engine_for_database, get_database_schema_string
from text2query.llm.prompt_loader import get_prompt_template
from text2query.llm.provider import get_llm_provider

logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 2000


def _json_safe(value):
    """Convert a single DataFrame cell into a JSON-serializable value.

    Postgres hands back types json.dumps can't encode: NUMERIC -> Decimal,
    DATE/TIMESTAMP -> date/datetime, and NULLs in numeric columns -> NaN.
    Left unhandled these raise inside json.dumps and surface as a bare 500.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):  # NaN, NaT, pd.NA — all become null
            return None
    except (TypeError, ValueError):
        pass  # non-scalar (e.g. array/list cell) — leave for json.dumps
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):  # numpy integer/bool scalars
        return value.item()
    return value


def _rows_to_json(df: pd.DataFrame) -> list[list]:
    """Convert a result DataFrame into JSON-safe row lists, preserving dtypes."""
    return [[_json_safe(v) for v in row] for row in df.itertuples(index=False, name=None)]


class RequestError(Exception):
    """A request-boundary or pipeline failure mapped to an HTTP status code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def parse_question(raw_body: bytes) -> str:
    """Validate and extract the question from a raw JSON request body."""
    try:
        payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError:
        raise RequestError(400, "Invalid JSON body.")

    question = payload.get("question") if isinstance(payload, dict) else None
    if not isinstance(question, str) or not question.strip():
        raise RequestError(400, "Field 'question' must be a non-empty string.")
    if len(question) > MAX_QUESTION_LENGTH:
        raise RequestError(400, f"Field 'question' exceeds {MAX_QUESTION_LENGTH} characters.")

    return question.strip()


def handle_query(llm, engine, schema: str, model: str, question: str) -> dict:
    """Generate SQL for the question, execute it, and return the response payload."""
    result = llm.generate_sql(question, schema, model)
    if result.error:
        raise RequestError(422, result.error)
    if not result.sql:
        raise RequestError(422, "Could not generate a safe SQL query for this question.")

    exec_result = execute_sql_query(engine, result.sql)
    if not exec_result.ok:
        raise RequestError(502, exec_result.error)

    df = exec_result.data
    return {
        "sql": result.sql,
        "columns": [str(c) for c in df.columns],
        "rows": _rows_to_json(df),
        "row_count": len(df),
        "error": None,
    }


class AppContext:
    """Process-wide state constructed once at server startup."""

    def __init__(self):
        self.engine = create_engine_for_database(DATABASE_URL)
        self.schema = get_database_schema_string(self.engine)
        get_prompt_template()  # fail fast on a missing/invalid template; caches it
        self.flags = GenerationFlags.from_env()
        self.llm = get_llm_provider()
        self.llm.warmup(DEFAULT_MODEL)


def _make_handler(ctx: AppContext) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _write_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._write_json(200, {"status": "ok"})
            else:
                self._write_json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/query":
                self._write_json(404, {"error": "not found"})
                return

            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""

            try:
                question = parse_question(raw)
                payload = handle_query(ctx.llm, ctx.engine, ctx.schema, DEFAULT_MODEL, question)
                self._write_json(200, payload)
            except RequestError as e:
                self._write_json(e.status, {"error": e.message})
            except Exception:
                logger.exception("Unhandled error while answering query")
                self._write_json(500, {"error": "Internal server error."})

        def log_message(self, format, *args):
            logger.info("%s - %s", self.address_string(), format % args)

    return Handler


def main():
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.WARNING),
        format="%(levelname)s %(name)s: %(message)s",
    )

    ctx = AppContext()
    enabled_flags = [name for name, value in ctx.flags.to_dict().items() if value]
    handler_cls = _make_handler(ctx)
    server = ThreadingHTTPServer(("0.0.0.0", SERVER_PORT), handler_cls)
    logger.warning(
        "text2query server listening on port %s (model=%s, flags=%s)",
        SERVER_PORT, DEFAULT_MODEL, ", ".join(enabled_flags) or "none",
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
