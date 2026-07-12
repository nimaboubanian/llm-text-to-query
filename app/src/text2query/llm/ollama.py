import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from text2query.core.config import (
    DEFAULT_MODEL, LLM_MAX_TOKENS, LLM_NUM_CTX, LLM_TEMPERATURE, LLM_TIMEOUT, OLLAMA_URL,
)
from text2query.llm.prompt_loader import get_prompt_template, render_prompt
from text2query.llm.service import _clean_sql_response

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    """Result of a single SQL-generation call."""

    sql: str | None
    raw_response: str | None = None
    prompt: str | None = None
    error: str | None = None


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
) -> GenerationResult:
    selected_model = model or DEFAULT_MODEL
    prompt = render_prompt(get_prompt_template(), schema_str, user_query)

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
        return GenerationResult(
            sql=_clean_sql_response(full_response),
            raw_response=full_response,
            prompt=prompt,
        )

    except TimeoutError:
        logger.warning("Generate request timed out (model=%r)", selected_model)
        return GenerationResult(
            sql=None, prompt=prompt, error="Request timed out. Model might be loading."
        )
    except urllib.error.URLError as e:
        logger.warning("Generate request failed (model=%r): %s", selected_model, e)
        return GenerationResult(sql=None, prompt=prompt, error=f"Connection failed: {e}")
