import os

OLLAMA_URL = "http://ollama:11434"

LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 2048

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5-coder:7b")

FRONTDESK_MODEL = os.getenv("FRONTDESK_MODEL", "llama3.2:3b")
FRONTDESK_TEMPERATURE = 0.4

BENCHMARK_SCALE_FACTOR = 1
BENCHMARK_NUM_SEEDS = int(os.getenv("BENCHMARK_NUM_SEEDS", "1"))
BENCHMARK_DATA_PATH = os.getenv("BENCHMARK_DATA_PATH")

_models_raw = os.getenv("BENCHMARK_MODELS", "")
BENCHMARK_MODELS = [m.strip() for m in _models_raw.split(",") if m.strip()][:3]

_query_ids_raw = os.getenv("BENCHMARK_QUERY_IDS", "all").strip().lower()
BENCHMARK_QUERY_IDS: list[str] | None = (
    None if _query_ids_raw in ("all", "")
    else [f"{int(q.strip()):02d}" for q in _query_ids_raw.split(",") if q.strip().isdigit()]
)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@postgres:5432/testdb")
