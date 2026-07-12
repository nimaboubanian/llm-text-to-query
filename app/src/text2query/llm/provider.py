from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class GenerationResult:
    """Result of a single SQL-generation call."""

    sql: str | None
    raw_response: str | None = None
    prompt: str | None = None
    error: str | None = None


class LLMProvider(ABC):
    """Interface for a chat/completion backend used to generate SQL."""

    @abstractmethod
    def generate_sql(
        self,
        user_query: str,
        schema_str: str,
        model: str | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        """Generate SQL for a natural-language question against the given schema."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """List models available on the backend."""

    @abstractmethod
    def warmup(self, model: str, timeout: int = 300) -> bool:
        """Preload a model into memory before timed generation."""


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    """Return the configured LLM provider."""
    from text2query.llm.ollama import OllamaProvider
    return OllamaProvider()
