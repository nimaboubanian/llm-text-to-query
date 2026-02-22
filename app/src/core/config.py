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

# Helper to get value: env var > yaml > default
def _get_config(key: str, default: Any, env_var: str | None = None) -> Any:
    """Get config value from env var, yaml, or default."""
    if env_var:
        env_value = os.getenv(env_var)
        if env_value is not None:
            return env_value

    if key in _yaml_config:
        return _yaml_config[key]

    return default


# Ollama Settings
OLLAMA_URL = _get_config("ollama_url", "http://ollama:11434", "OLLAMA_URL")
OLLAMA_TIMEOUT = int(_get_config("ollama_timeout", 300, "OLLAMA_TIMEOUT"))

# LLM Generation Settings
LLM_TEMPERATURE = float(_get_config("temperature", 0.1, "LLM_TEMPERATURE"))
LLM_MAX_TOKENS = int(_get_config("max_tokens", 2048, "LLM_MAX_TOKENS"))

# Model Settings
DEFAULT_MODEL = _get_config("default_model", "qwen2.5-coder:7b", "DEFAULT_MODEL")
AVAILABLE_MODELS = [DEFAULT_MODEL]

# LLM Prompt Template
LLM_PROMPT_TEMPLATE = _get_config(
    "prompt_template",
    """You are a PostgreSQL query generator.
Given the following database schema:
{schema}

Generate a query to answer: {query}

Rules:
- Return ONLY the query, nothing else
- No explanations, no comments, no markdown
- Only use tables and columns from the schema above
- Use PostgreSQL syntax
""",
    "LLM_PROMPT_TEMPLATE",
)

# Benchmark Settings
BENCHMARK_SCALE_FACTOR = int(_get_config("benchmark_scale_factor", 1, "BENCHMARK_SCALE_FACTOR"))
BENCHMARK_DATA_PATH = _get_config("benchmark_data_path", None, "BENCHMARK_DATA_PATH")
BENCHMARK_SCHEMA_PATH = Path(_get_config("benchmark_schema_path", "benchmark/.tpch/schema.sql", "BENCHMARK_SCHEMA_PATH"))
BENCHMARK_OUTPUT_DIR = Path(_get_config("benchmark_output_dir", "benchmark/queries", "BENCHMARK_OUTPUT_DIR"))

# Database Settings
DATABASE_URL = _get_config("database_url", "postgresql://user:password@postgres:5432/testdb", "DATABASE_URL")
