import os
from pathlib import Path

# Point the SQL-generation prompt loader at the real repo-root template when
# tests run outside Docker (where PROMPT_TEMPLATE_PATH isn't already set by
# compose). Must run before text2query.core.config is first imported.
os.environ.setdefault(
    "PROMPT_TEMPLATE_PATH",
    str(Path(__file__).resolve().parents[2] / "prompts" / "sql_generation.txt"),
)
