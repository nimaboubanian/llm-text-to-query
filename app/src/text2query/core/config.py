import os
from dataclasses import dataclass


def _env(name: str, default, cast):
    """Read a value from the environment, falling back to default if unset or unparseable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return cast(raw)
    except ValueError:
        return default


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")

LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING")

LLM_TEMPERATURE = _env("LLM_TEMPERATURE", 0.1, float)
LLM_NUM_CTX = _env("LLM_NUM_CTX", 4096, int)
LLM_MAX_TOKENS = _env("LLM_MAX_TOKENS", 2048, int)

# Whole-generation timeout (seconds) for a single non-streaming request. With
# stream=false the model must finish within this window with no bytes flowing,
# so it needs to be generous on CPU-only setups where a 7B model is slow.
LLM_TIMEOUT = _env("LLM_TIMEOUT", 600, int)

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5-coder:7b")

SERVER_PORT = _env("SERVER_PORT", 8000, int)

BENCHMARK_SCALE_FACTOR = _env("BENCHMARK_SCALE_FACTOR", 1, int)
BENCHMARK_NUM_SEEDS = _env("BENCHMARK_NUM_SEEDS", 1, int)
BENCHMARK_DATA_PATH = os.getenv("BENCHMARK_DATA_PATH")

_models_raw = os.getenv("BENCHMARK_MODELS", "")
BENCHMARK_MODELS = [m.strip() for m in _models_raw.split(",") if m.strip()]

_query_ids_raw = os.getenv("BENCHMARK_QUERY_IDS", "all").strip().lower()
BENCHMARK_QUERY_IDS: list[str] | None = (
    None if _query_ids_raw in ("all", "")
    else [f"{int(q.strip()):02d}" for q in _query_ids_raw.split(",") if q.strip().isdigit()]
)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@postgres:5432/testdb")


def _bool(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class PromptFlags:
    """Togglable prompt-engineering features. All-off = experimental baseline."""
    schema_ddl: bool = False
    schema_fk: bool = False
    schema_descriptions: bool = False
    schema_samples: bool = False
    xml_structure: bool = False
    few_shot: int = 0  # 0 = off; clamped to [0, 3] (research: >3 degrades <10B models)
    planning: bool = False
    strict_output: bool = False
    retry_on_error: bool = False


PROMPT_FLAGS = PromptFlags(
    schema_ddl=_env("PROMPT_SCHEMA_DDL", False, _bool),
    schema_fk=_env("PROMPT_SCHEMA_FK", False, _bool),
    schema_descriptions=_env("PROMPT_SCHEMA_DESCRIPTIONS", False, _bool),
    schema_samples=_env("PROMPT_SCHEMA_SAMPLES", False, _bool),
    xml_structure=_env("PROMPT_XML_STRUCTURE", False, _bool),
    few_shot=max(0, min(3, _env("PROMPT_FEW_SHOT", 0, int))),
    planning=_env("PROMPT_PLANNING", False, _bool),
    strict_output=_env("PROMPT_STRICT_OUTPUT", False, _bool),
    retry_on_error=_env("RETRY_ON_ERROR", False, _bool),
)
