import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from text2query.core.config import (
    DEFAULT_MODEL, LLM_MAX_TOKENS, LLM_NUM_CTX, LLM_TEMPERATURE, LLM_TIMEOUT, OLLAMA_URL,
    PROMPT_FLAGS,
)
from text2query.llm.prompt_builder import build_prompt

logger = logging.getLogger(__name__)


def _is_single_statement(sql: str) -> bool:
    """Reject multi-statement SQL to prevent piggyback attacks."""
    stripped = sql.strip().rstrip(";")
    return ";" not in stripped


def _is_select_only(sql: str) -> bool:
    """Accept only SELECT statements (including CTEs and set operations); reject DDL/DML."""
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        parsed = None

    if parsed is not None:
        return isinstance(parsed, (exp.Select, exp.Union))

    # sqlglot couldn't parse it (e.g. dialect quirks) — fall back to a conservative
    # keyword-prefix check so valid SELECTs aren't unfairly rejected.
    return bool(re.match(r"(?i)^\s*(SELECT|WITH)\b", sql))


def _is_safe_sql(sql: str) -> bool:
    return _is_single_statement(sql) and _is_select_only(sql)


def _clean_sql_response(response: str) -> str | None:
    if not response:
        return None

    match = re.search(r"```(?:sql)?\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
    if match:
        sql = match.group(1).strip()
        return sql if _is_safe_sql(sql) else None

    match = re.search(r"(SELECT|WITH)\s+.*?;", response, re.DOTALL | re.IGNORECASE)
    if match:
        sql = match.group(0).strip()
        return sql if _is_safe_sql(sql) else None

    return None


@dataclass
class GenerationResult:
    """Result of a single SQL-generation call."""

    sql: str | None
    raw_response: str | None = None
    prompt: str | None = None
    error: str | None = None
    retried: bool = False
    first_prompt: str | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    duration_seconds: float | None = None


def _post_json(url: str, payload: dict, timeout: int) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def warmup(model: str) -> bool:
    """Preload a model into memory before timed generation.

    Sends an empty-prompt generate request, which makes Ollama load the model
    and return immediately without generating tokens — avoiding a cold-load
    timeout on the first real query. Returns True if the model loaded.
    """
    try:
        status, _ = _post_json(
            f"{OLLAMA_URL}/api/generate",
            {
                "model": model,
                "prompt": "",
                "stream": False,
                "options": {"num_ctx": LLM_NUM_CTX},
            },
            300,
        )
        return status == 200
    except (urllib.error.URLError, TimeoutError) as e:
        logger.warning("Failed to warm up model %r: %s", model, e)
        return False


def generate_sql(
    user_query: str,
    schema_str: str,
    model: str | None = None,
    seed: int | None = None,
    flags=None,
) -> GenerationResult:
    selected_model = model or DEFAULT_MODEL
    prompt = build_prompt(flags or PROMPT_FLAGS, schema_str, user_query)
    return _generate(prompt, selected_model, seed)


def _generate(prompt: str, selected_model: str, seed: int | None) -> GenerationResult:
    options = {
        "temperature": LLM_TEMPERATURE,
        "num_predict": LLM_MAX_TOKENS,
        "num_ctx": LLM_NUM_CTX,
    }
    if seed is not None:
        options["seed"] = seed

    try:
        status, data = _post_json(
            f"{OLLAMA_URL}/api/generate",
            {
                "model": selected_model,
                "prompt": prompt,
                "stream": False,
                "options": options,
            },
            LLM_TIMEOUT,
        )

        if status == 404:
            return GenerationResult(
                sql=None, prompt=prompt, error=f"Model '{selected_model}' not found."
            )

        if status != 200:
            return GenerationResult(
                sql=None, prompt=prompt, error=f"LLM API error: {status}"
            )

        full_response = data.get("response", "")
        duration_ns = data.get("total_duration")
        return GenerationResult(
            sql=_clean_sql_response(full_response),
            raw_response=full_response,
            prompt=prompt,
            prompt_eval_count=data.get("prompt_eval_count"),
            eval_count=data.get("eval_count"),
            duration_seconds=duration_ns / 1e9 if duration_ns is not None else None,
        )

    except TimeoutError:
        logger.warning("Generate request timed out (model=%r)", selected_model)
        return GenerationResult(
            sql=None, prompt=prompt, error="Request timed out. Model might be loading."
        )
    except urllib.error.URLError as e:
        logger.warning("Generate request failed (model=%r): %s", selected_model, e)
        return GenerationResult(sql=None, prompt=prompt, error=f"Connection failed: {e}")


def generate_sql_with_retry(
    user_query: str,
    schema_str: str,
    model: str | None = None,
    seed: int | None = None,
    validate=None,
    flags=None,
) -> GenerationResult:
    """Single execution-guided retry: re-prompt once with the failure appended.

    `validate(sql)` returns an error string (fed back to the model) or None.
    Transport errors (timeout, 404) are returned as-is — feedback can't fix those.
    """
    flags = flags or PROMPT_FLAGS
    result = generate_sql(user_query, schema_str, model, seed=seed, flags=flags)
    if not flags.retry_on_error or result.error:
        return result

    if result.sql is None:
        reason = "Your previous answer contained no SQL query."
    elif validate is not None and (err := validate(result.sql)):
        reason = f"Your previous query failed with this PostgreSQL error: {err}"
    else:
        return result

    # Wording here deliberately overlaps both _RULES_STRICT ("Return ONLY the SQL
    # query... no markdown", gated on PROMPT_STRICT_OUTPUT) and _RULES_MINIMAL
    # ("Only use tables and columns from the schema above", always included) in
    # prompt_builder.py, so RETRY_ON_ERROR=true is not a clean ablation of retry
    # independent of those rules.
    retry_prompt = (
        f"{result.prompt}\n\n"
        f"{reason}\n"
        "Do not repeat your previous answer. Re-derive the query from the schema above, "
        "using only tables and columns that appear in it. "
        "Return ONLY the corrected SQL query, no explanation, no markdown."
    )
    retried = _generate(retry_prompt, model or DEFAULT_MODEL, seed)
    retried.retried = True
    retried.first_prompt = result.prompt
    return retried
