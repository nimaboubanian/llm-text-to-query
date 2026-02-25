import os
from pathlib import Path

OLLAMA_URL = "http://ollama:11434"
OLLAMA_TIMEOUT = 300

LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 2048

DEFAULT_MODEL = "qwen2.5-coder:7b"
AVAILABLE_MODELS = [DEFAULT_MODEL]

BENCHMARK_SCALE_FACTOR = 1
BENCHMARK_DATA_PATH = os.getenv("BENCHMARK_DATA_PATH")
BENCHMARK_SCHEMA_PATH = Path("benchmark/.tpch/schema.sql")
BENCHMARK_OUTPUT_DIR = Path("benchmark/queries")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@postgres:5432/testdb")
