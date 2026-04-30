"""Tests for front-desk routing and summarization."""
from unittest.mock import patch

import pandas as pd

from text2query.cli.frontdesk import quick_classify, classify_intent, summarize_results


# ── Heuristic pre-filter ──────────────────────────────────────────────

TABLES = ["customers", "products", "orders"]


def test_quick_classify_select_statement():
    assert quick_classify("SELECT * FROM orders", TABLES) == "sql"


def test_quick_classify_data_question_with_table():
    assert quick_classify("how many customers are there", TABLES) == "sql"


def test_quick_classify_singular_table_match():
    """'product' should match the 'products' table."""
    assert quick_classify("show me the top product by price", TABLES) == "sql"


def test_quick_classify_greeting():
    assert quick_classify("hi", TABLES) == "conversation"
    assert quick_classify("Hello!", TABLES) == "conversation"
    assert quick_classify("thanks", TABLES) == "conversation"


def test_quick_classify_meta_question():
    assert quick_classify("what model are you using?", TABLES) == "conversation"


def test_quick_classify_ambiguous_returns_none():
    assert quick_classify("tell me about the data", TABLES) is None
    assert quick_classify("what is the weather like?", TABLES) is None


def test_quick_classify_data_word_without_table_is_ambiguous():
    """Data-intent words present but no table name mentioned → ambiguous, not sql."""
    assert quick_classify("how many things are there", TABLES) is None


# ── LLM intent classification ────────────────────────────────────────

@patch("text2query.cli.frontdesk.chat_with_model")
def test_classify_routes_sql_intent(mock_chat):
    mock_chat.return_value = "SQL_QUERY"
    intent, response = classify_intent("how many orders?", "testdb", TABLES, "qwen2.5:3b")
    assert intent == "sql"
    assert response is None


@patch("text2query.cli.frontdesk.chat_with_model")
def test_classify_routes_conversation(mock_chat):
    mock_chat.return_value = "CONVERSATION\nHello! I can help you query the database."
    intent, response = classify_intent("hi there", "testdb", TABLES, "qwen2.5:3b")
    assert intent == "conversation"
    assert "Hello" in response


@patch("text2query.cli.frontdesk.chat_with_model")
def test_classify_defaults_to_sql_on_garbage(mock_chat):
    mock_chat.return_value = "asdf random garbage"
    intent, response = classify_intent("something weird", "testdb", TABLES, "qwen2.5:3b")
    assert intent == "sql"


@patch("text2query.cli.frontdesk.chat_with_model")
def test_classify_defaults_to_conversation_on_failure(mock_chat):
    mock_chat.return_value = None
    intent, _ = classify_intent("anything", "testdb", TABLES, "qwen2.5:3b")
    assert intent == "conversation"


# ── Result summarization ─────────────────────────────────────────────

@patch("text2query.cli.frontdesk.chat_with_model")
def test_summarize_small_dataframe(mock_chat):
    mock_chat.return_value = "There are 3 customers."
    df = pd.DataFrame({"name": ["Alice", "Bob", "Charlie"], "age": [30, 25, 35]})
    result = summarize_results("how many customers?", df, "testdb", TABLES, "qwen2.5:3b")
    assert result == "There are 3 customers."
    # Verify the full table was passed in the prompt (not a summary)
    prompt = mock_chat.call_args[0][0][0]["content"]
    assert "Alice" in prompt
    assert "Charlie" in prompt


@patch("text2query.cli.frontdesk.chat_with_model")
def test_summarize_large_dataframe_uses_head(mock_chat):
    mock_chat.return_value = "Summary of 50 rows."
    df = pd.DataFrame({"id": range(50), "value": range(50)})
    summarize_results("show all", df, "testdb", TABLES, "qwen2.5:3b")
    prompt = mock_chat.call_args[0][0][0]["content"]
    assert "First 5 rows" in prompt
    assert "Numeric summary" in prompt


@patch("text2query.cli.frontdesk.chat_with_model")
def test_summarize_empty_dataframe(mock_chat):
    mock_chat.return_value = "No matching results found."
    df = pd.DataFrame()
    result = summarize_results("find something", df, "testdb", TABLES, "qwen2.5:3b")
    assert result == "No matching results found."
    prompt = mock_chat.call_args[0][0][0]["content"]
    assert "no results" in prompt.lower()


def test_summarize_error_returns_none():
    result = summarize_results("query", "SQL error: table not found", "testdb", TABLES, "qwen2.5:3b")
    assert result is None
