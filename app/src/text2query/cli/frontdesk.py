import re

import pandas as pd

from text2query.core.config import FRONTDESK_TEMPERATURE
from text2query.llm.service import chat_with_model
from text2query.llm.prompts import (
    INTENT_CLASSIFY_TEMPLATE,
    SUMMARIZE_RESULTS_TEMPLATE,
    SUMMARIZE_EMPTY_TEMPLATE,
)

_GREETING_PATTERNS = {"hi", "hello", "hey", "thanks", "thank you", "bye", "goodbye"}
_META_PREFIXES = ("what model", "what are you", "who are you", "are you")
_SQL_KEYWORDS = ("select", "insert", "update", "delete", "with")
_DATA_WORDS = re.compile(
    r"\b(how many|list|show|count|total|average|sum|top|last|first|find|get|"
    r"number of|biggest|smallest|most|least|maximum|minimum|highest|lowest)\b",
    re.IGNORECASE,
)


def quick_classify(user_input: str, table_names: list[str]) -> str | None:
    """Fast heuristic intent check. Returns 'sql', 'conversation', or None (ambiguous)."""
    stripped = user_input.strip().lower()

    # Direct SQL statement
    if any(stripped.startswith(kw) for kw in _SQL_KEYWORDS):
        return "sql"

    # Greeting or very short social input
    if stripped.rstrip("!?.") in _GREETING_PATTERNS:
        return "conversation"

    # Meta question about the tool
    if any(stripped.startswith(p) for p in _META_PREFIXES):
        return "conversation"

    # Data-intent words + table name mentioned
    if _DATA_WORDS.search(stripped):
        lower_input = stripped
        for table in table_names:
            # Match table name or a rough singular form (e.g. "customer" matches "customers")
            if table.lower() in lower_input or table.lower().rstrip("s") in lower_input:
                return "sql"

    return None


def classify_intent(
    user_input: str,
    db_name: str,
    tables: list[str],
    model: str,
) -> tuple[str, str | None]:
    """Classify user input via the front-desk LLM.

    Returns (intent, response) where intent is 'sql' or 'conversation',
    and response is set only for conversation.
    """
    system_prompt = INTENT_CLASSIFY_TEMPLATE.format(
        db_name=db_name,
        tables=", ".join(tables),
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    raw = chat_with_model(messages, model, FRONTDESK_TEMPERATURE)
    if not raw:
        return ("conversation", None)  # safe fallback: don't execute SQL on LLM failure

    lines = raw.strip().split("\n", 1)
    label = lines[0].strip().upper()

    if "CONVERSATION" in label:
        response = lines[1].strip() if len(lines) > 1 else None
        return ("conversation", response)

    return ("sql", None)


def summarize_results(
    question: str,
    result,
    db_name: str,
    tables: list[str],
    model: str,
) -> str | None:
    """Generate a natural-language summary of query results."""
    if isinstance(result, str):
        return None

    if result.empty:
        prompt = SUMMARIZE_EMPTY_TEMPLATE.format(
            question=question,
            db_name=db_name,
            tables=", ".join(tables),
        )
    else:
        result_summary = _prepare_result_summary(result)
        prompt = SUMMARIZE_RESULTS_TEMPLATE.format(
            question=question,
            row_count=len(result),
            result_summary=result_summary,
        )

    messages = [{"role": "user", "content": prompt}]
    return chat_with_model(messages, model, FRONTDESK_TEMPERATURE)


def _prepare_result_summary(df: pd.DataFrame) -> str:
    """Build a text digest of a DataFrame for the summarize prompt."""
    if len(df) <= 20:
        return df.to_string(index=False)

    parts = [f"First 5 rows:\n{df.head(5).to_string(index=False)}"]

    numeric = df.select_dtypes(include="number")
    if not numeric.empty:
        parts.append(f"\nNumeric summary:\n{numeric.describe().to_string()}")

    return "\n".join(parts)
