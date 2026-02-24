"""Application configuration with hardcoded defaults."""

import os
from pathlib import Path
from typing import Any

import yaml


def _load_yaml_config() -> dict[str, Any]:
    """Load optional config.yaml if it exists."""
    config_path = Path("config.yaml")
    if not config_path.exists():
        return {}

    try:
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


# Load optional YAML overrides
_yaml_config = _load_yaml_config()

def _get_config(key: str, default: Any, env_var: str | None = None) -> Any:
    """Get config value from env var, yaml, or default."""
    if env_var:
        env_value = os.getenv(env_var)
        if env_value is not None:
            return env_value

    if key in _yaml_config:
        return _yaml_config[key]

    return default


OLLAMA_URL = "http://ollama:11434"
OLLAMA_TIMEOUT = 300

LLM_TEMPERATURE = float(_get_config("temperature", 0.1, "LLM_TEMPERATURE"))
LLM_MAX_TOKENS = int(_get_config("max_tokens", 2048, "LLM_MAX_TOKENS"))

DEFAULT_MODEL = _get_config("default_model", "qwen2.5-coder:7b", "DEFAULT_MODEL")
AVAILABLE_MODELS = [DEFAULT_MODEL]

BENCHMARK_SCALE_FACTOR = int(_get_config("benchmark_scale_factor", 1, "BENCHMARK_SCALE_FACTOR"))
BENCHMARK_DATA_PATH = os.getenv("BENCHMARK_DATA_PATH")
BENCHMARK_SCHEMA_PATH = Path("benchmark/.tpch/schema.sql")
BENCHMARK_OUTPUT_DIR = Path("benchmark/queries")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@postgres:5432/testdb")
