import re
from functools import lru_cache
from pathlib import Path

from text2query.core.config import PROMPT_TEMPLATE_PATH

MAX_TEMPLATE_SIZE = 16 * 1024

REQUIRED_PLACEHOLDERS = ("{schema}", "{query}")

_PLACEHOLDER_PATTERN = re.compile(r"\{schema\}|\{query\}")


class PromptTemplateError(Exception):
    """Raised when the SQL-generation prompt template is missing or malformed."""


def load_prompt_template(path: str | Path | None = None) -> str:
    """Load and validate the SQL-generation prompt template from disk.

    The security boundary for generated SQL is output-side (statement-type and
    read-only-transaction checks in llm/service.py and database/executor.py).
    This validation only guards against operator misconfiguration — a missing
    mount, a truncated file, a template that can't be filled in.
    """
    template_path = Path(path) if path is not None else Path(PROMPT_TEMPLATE_PATH)
    try:
        text = template_path.read_text(encoding="utf-8")
    except OSError as e:
        raise PromptTemplateError(
            f"Could not read prompt template at '{template_path}' — check that "
            f"PROMPT_TEMPLATE_PATH is set correctly and the file is mounted: {e}"
        ) from e
    except UnicodeDecodeError as e:
        raise PromptTemplateError(
            f"Prompt template '{template_path}' is not valid UTF-8 text — "
            f"PROMPT_TEMPLATE_PATH may be pointing at a binary file: {e}"
        ) from e

    if len(text.encode("utf-8")) > MAX_TEMPLATE_SIZE:
        raise PromptTemplateError(
            f"Prompt template '{template_path}' exceeds the {MAX_TEMPLATE_SIZE}-byte limit."
        )

    missing = [p for p in REQUIRED_PLACEHOLDERS if p not in text]
    if missing:
        raise PromptTemplateError(
            f"Prompt template '{template_path}' is missing required placeholder(s): "
            f"{', '.join(missing)}."
        )

    return text


@lru_cache(maxsize=1)
def get_prompt_template() -> str:
    """Return the process-wide SQL-generation template, loaded once from disk.

    The template is read and validated on first use and cached for the process
    lifetime — so every query in a benchmark run (and every request the server
    answers) uses the same template the fingerprint was computed from, and
    editing the file requires a restart to take effect (like the cached schema).
    Tests that need a fresh read pass an explicit path to load_prompt_template().
    """
    return load_prompt_template()


def render_prompt(template: str, schema_str: str, user_query: str) -> str:
    """Substitute the schema and question into the template.

    Single-pass token replacement over the original template text — not
    str.format — so `{schema}`/`{query}`-like text inside the schema or the
    user's question is never rescanned and can't be reinterpreted as template
    syntax.
    """
    def _sub(match: re.Match) -> str:
        return schema_str if match.group() == "{schema}" else user_query

    return _PLACEHOLDER_PATTERN.sub(_sub, template)
