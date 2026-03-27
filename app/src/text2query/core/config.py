import os

OLLAMA_URL = "http://ollama:11434"

LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 2048

DEFAULT_MODEL = "qwen2.5-coder:7b"

BENCHMARK_SCALE_FACTOR = 1
BENCHMARK_NUM_SEEDS = int(os.getenv("BENCHMARK_NUM_SEEDS", "1"))
BENCHMARK_DATA_PATH = os.getenv("BENCHMARK_DATA_PATH")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@postgres:5432/testdb")
