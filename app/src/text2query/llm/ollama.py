import json
import logging
from collections.abc import Callable, Generator

import requests

from text2query.core.config import (
    DEFAULT_MODEL, LLM_MAX_TOKENS, LLM_NUM_CTX, LLM_TEMPERATURE, OLLAMA_URL,
)
from text2query.llm.provider import LLMProvider
from text2query.llm.service import _build_prompt, _clean_sql_response

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """LLMProvider backed by a local Ollama server."""

    def __init__(self, base_url: str = OLLAMA_URL):
        self.base_url = base_url

    def abort(self, model: str | None = None) -> bool:
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": model or DEFAULT_MODEL, "keep_alive": 0},
                timeout=5,
            )
            return resp.status_code == 200
        except requests.exceptions.RequestException as e:
            logger.warning("Failed to abort generation for model %r: %s", model, e)
            return False

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

    def chat(self, messages: list[dict], model: str, temperature: float = 0.4) -> str | None:
        try:
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature},
                },
                timeout=30,
            )
            if resp.status_code != 200:
                return None
            return resp.json().get("message", {}).get("content")
        except requests.exceptions.RequestException as e:
            logger.warning("Chat request to %s failed (model=%r): %s", self.base_url, model, e)
            return None

    def generate_sql_streaming(
        self,
        user_query: str,
        schema_str: str,
        model: str | None = None,
        stop_check: Callable[[], bool] | None = None,
        seed: int | None = None,
    ) -> Generator[dict, None, None]:
        selected_model = model or DEFAULT_MODEL
        prompt = _build_prompt(user_query, schema_str)

        full_response = ""
        stopped = False
        session = None
        response = None

        options = {
            "temperature": LLM_TEMPERATURE,
            "num_predict": LLM_MAX_TOKENS,
            "num_ctx": LLM_NUM_CTX,
        }
        if seed is not None:
            options["seed"] = seed

        try:
            session = requests.Session()
            session.headers.update({"Connection": "close"})

            response = session.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": selected_model,
                    "prompt": prompt,
                    "stream": True,
                    "options": options,
                },
                timeout=120,
                stream=True,
            )

            if response.status_code == 404:
                yield {"type": "error", "message": f"Model '{selected_model}' not found."}
                return

            if response.status_code != 200:
                yield {"type": "error", "message": f"LLM API error: {response.status_code}"}
                return

            for line in response.iter_lines():
                # Check stop request
                if stop_check and stop_check():
                    stopped = True
                    response.close()
                    self.abort(selected_model)
                    yield {"type": "stopped", "partial_response": full_response}
                    return

                if not line:
                    continue

                try:
                    data = json.loads(line)
                    token = data.get("response", "")
                    if token:
                        full_response += token
                        yield {"type": "token", "content": token}

                    if data.get("done"):
                        yield {
                            "type": "done",
                            "full_response": full_response,
                            "sql": _clean_sql_response(full_response),
                            "prompt": prompt,
                        }
                        return
                except json.JSONDecodeError as e:
                    logger.debug("Skipping malformed stream line: %s", e)
                    continue

            # Stream ended without "done" - return what we have
            yield {
                "type": "done",
                "full_response": full_response,
                "sql": _clean_sql_response(full_response),
                "prompt": prompt,
            }

        except requests.exceptions.Timeout:
            logger.warning("Generate request timed out (model=%r)", selected_model)
            yield {"type": "error", "message": "Request timed out. Model might be loading."}
        except requests.exceptions.RequestException as e:
            if not stopped:
                logger.warning("Generate request failed (model=%r): %s", selected_model, e)
                yield {"type": "error", "message": f"Connection failed: {e}"}
        finally:
            if response:
                response.close()
            if session:
                session.close()
