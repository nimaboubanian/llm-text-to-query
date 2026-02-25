import os
from pathlib import Path

import yaml

_yaml = {}
try:
    with open("config.yaml") as f:
        _yaml = yaml.safe_load(f) or {}
except Exception:
    pass


def _get(key: str, default, env_var: str | None = None):
    if env_var:
        val = os.getenv(env_var)
        if val is not None:
            return val
    return _yaml.get(key, default)


OLLAMA_URL = "http://ollama:11434"
OLLAMA_TIMEOUT = 300

LLM_TEMPERATURE = float(_get("temperature", 0.1, "LLM_TEMPERATURE"))
LLM_MAX_TOKENS = int(_get("max_tokens", 2048, "LLM_MAX_TOKENS"))

DEFAULT_MODEL = _get("default_model", "qwen2.5-coder:7b", "DEFAULT_MODEL")
AVAILABLE_MODELS = [DEFAULT_MODEL]

BENCHMARK_SCALE_FACTOR = int(_get("benchmark_scale_factor", 1, "BENCHMARK_SCALE_FACTOR"))
BENCHMARK_DATA_PATH = os.getenv("BENCHMARK_DATA_PATH")
BENCHMARK_SCHEMA_PATH = Path("benchmark/.tpch/schema.sql")
BENCHMARK_OUTPUT_DIR = Path("benchmark/queries")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@postgres:5432/testdb")
