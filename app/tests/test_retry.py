from text2query.core.config import PromptFlags
from text2query.llm import ollama

RETRY_ON = PromptFlags(retry_on_error=True)


def _fake_transport(responses):
    """Return a _post_json stand-in yielding canned Ollama responses in order."""
    calls = []

    def fake(url, payload, timeout):
        calls.append(payload)
        return 200, {"response": responses[len(calls) - 1]}

    return fake, calls


def test_no_retry_when_flag_off(monkeypatch):
    fake, calls = _fake_transport(["SELECT 1;"])
    monkeypatch.setattr(ollama, "_post_json", fake)
    result = ollama.generate_sql_with_retry(
        "q", "s", flags=PromptFlags(), validate=lambda sql: "boom",
    )
    assert len(calls) == 1 and result.retried is False


def test_retry_on_validator_error_appends_error_text(monkeypatch):
    fake, calls = _fake_transport(["SELECT bad;", "SELECT good;"])
    monkeypatch.setattr(ollama, "_post_json", fake)
    result = ollama.generate_sql_with_retry(
        "q", "s", flags=RETRY_ON,
        validate=lambda sql: 'column "bad" does not exist' if "bad" in sql else None,
    )
    assert len(calls) == 2
    assert 'column "bad" does not exist' in calls[1]["prompt"]
    assert result.retried is True and result.sql == "SELECT good;"


def test_retry_on_extraction_failure(monkeypatch):
    fake, calls = _fake_transport(["I cannot write SQL, sorry!", "SELECT 1;"])
    monkeypatch.setattr(ollama, "_post_json", fake)
    result = ollama.generate_sql_with_retry("q", "s", flags=RETRY_ON, validate=None)
    assert len(calls) == 2 and result.retried is True and result.sql == "SELECT 1;"


def test_no_second_retry(monkeypatch):
    fake, calls = _fake_transport(["SELECT bad;", "SELECT still_bad;"])
    monkeypatch.setattr(ollama, "_post_json", fake)
    result = ollama.generate_sql_with_retry(
        "q", "s", flags=RETRY_ON, validate=lambda sql: "always broken",
    )
    assert len(calls) == 2  # exactly one retry, result returned as-is
    assert result.retried is True


def test_retry_prompt_excludes_previous_answer(monkeypatch):
    fake, calls = _fake_transport(["RAW_MARKER SELECT bad;", "SELECT good;"])
    monkeypatch.setattr(ollama, "_post_json", fake)
    result = ollama.generate_sql_with_retry(
        "q", "SCHEMA_MARKER", flags=RETRY_ON,
        validate=lambda sql: 'relation "customers" does not exist' if "bad" in sql else None,
    )
    assert result.retried is True
    retry_prompt = calls[1]["prompt"]
    assert "RAW_MARKER" not in retry_prompt          # no verbatim previous answer
    assert "does not exist" in retry_prompt          # error is fed back
    assert "SCHEMA_MARKER" in retry_prompt           # original prompt retained


def test_retried_result_preserves_first_prompt(monkeypatch):
    fake, calls = _fake_transport(["SELECT bad;", "SELECT still_bad;"])
    monkeypatch.setattr(ollama, "_post_json", fake)
    result = ollama.generate_sql_with_retry(
        "q", "s", flags=RETRY_ON, validate=lambda sql: "boom",
    )
    assert result.retried is True
    assert result.first_prompt is not None
    assert result.first_prompt != result.prompt


def test_generate_captures_telemetry(monkeypatch):
    def fake_post(url, payload, timeout):
        return 200, {"response": "```sql\nSELECT 1;\n```",
                     "prompt_eval_count": 2500, "eval_count": 120,
                     "total_duration": 63_000_000_000}
    monkeypatch.setattr(ollama, "_post_json", fake_post)
    result = ollama._generate("p", "m", 1)
    assert result.prompt_eval_count == 2500
    assert result.eval_count == 120
    assert result.duration_seconds == 63.0
