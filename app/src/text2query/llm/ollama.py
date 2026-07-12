import logging

import requests

from text2query.core.config import (
    DEFAULT_MODEL, LLM_MAX_TOKENS, LLM_NUM_CTX, LLM_TEMPERATURE, OLLAMA_URL,
)
from text2query.llm.provider import GenerationResult, LLMProvider
from text2query.llm.service import _build_prompt, _clean_sql_response

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """LLMProvider backed by a local Ollama server."""

    def __init__(self, base_url: str = OLLAMA_URL):
        self.base_url = base_url

    def list_models(self) -> list[str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except requests.exceptions.RequestException as e:
            logger.warning("Failed to list models from %s: %s", self.base_url, e)
        return []

    def warmup(self, model: str, timeout: int = 300) -> bool:
        """Preload a model into memory before timed generation.

        Sends an empty-prompt generate request, which makes Ollama load the model
        and return immediately without generating tokens — avoiding a cold-load
        timeout on the first real query. Returns True if the model loaded.
        """
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": "",
                    "stream": False,
                    "options": {"num_ctx": LLM_NUM_CTX},
                },
                timeout=timeout,
            )
            return resp.status_code == 200
        except requests.exceptions.RequestException as e:
            logger.warning("Failed to warm up model %r: %s", model, e)
            return False

    def generate_sql(
        self,
        user_query: str,
        schema_str: str,
        model: str | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        selected_model = model or DEFAULT_MODEL
        prompt = _build_prompt(user_query, schema_str)

        options = {
            "temperature": LLM_TEMPERATURE,
            "num_predict": LLM_MAX_TOKENS,
            "num_ctx": LLM_NUM_CTX,
        }
        if seed is not None:
            options["seed"] = seed

        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": selected_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": options,
                },
                timeout=120,
            )

            if resp.status_code == 404:
                return GenerationResult(
                    sql=None, prompt=prompt, error=f"Model '{selected_model}' not found."
                )

            if resp.status_code != 200:
                return GenerationResult(
                    sql=None, prompt=prompt, error=f"LLM API error: {resp.status_code}"
                )

            full_response = resp.json().get("response", "")
            return GenerationResult(
                sql=_clean_sql_response(full_response),
                raw_response=full_response,
                prompt=prompt,
            )

        except requests.exceptions.Timeout:
            logger.warning("Generate request timed out (model=%r)", selected_model)
            return GenerationResult(
                sql=None, prompt=prompt, error="Request timed out. Model might be loading."
            )
        except requests.exceptions.RequestException as e:
            logger.warning("Generate request failed (model=%r): %s", selected_model, e)
            return GenerationResult(sql=None, prompt=prompt, error=f"Connection failed: {e}")
