from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from functools import lru_cache


class LLMProvider(ABC):
    """Interface for a chat/completion backend used to generate SQL and converse."""

    @abstractmethod
    def generate_sql_streaming(
        self,
        user_query: str,
        schema_str: str,
        model: str | None = None,
        stop_check: Callable[[], bool] | None = None,
        seed: int | None = None,
    ) -> Generator[dict, None, None]:
        """Stream SQL generation. Yields token/done/stopped/error dicts."""

    @abstractmethod
    def chat(self, messages: list[dict], model: str, temperature: float = 0.4) -> str | None:
        """Send a chat-style request. Returns the response text, or None on failure."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """List models available on the backend."""

    @abstractmethod
    def abort(self, model: str | None = None) -> bool:
        """Abort an in-flight generation for the given model."""

    @abstractmethod
    def warmup(self, model: str, timeout: int = 300) -> bool:
        """Preload a model into memory before timed generation."""


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    """Return the configured LLM provider."""
    from text2query.llm.ollama import OllamaProvider
    return OllamaProvider()
