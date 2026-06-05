from text2query.core.config import _env_int, _env_float


def test_env_int_unset_returns_default(monkeypatch):
    monkeypatch.delenv("LLM_NUM_CTX", raising=False)
    assert _env_int("LLM_NUM_CTX", 4096) == 4096


def test_env_int_valid_is_parsed(monkeypatch):
    monkeypatch.setenv("LLM_NUM_CTX", "8192")
    assert _env_int("LLM_NUM_CTX", 4096) == 8192


def test_env_int_unparseable_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_NUM_CTX", "not-a-number")
    assert _env_int("LLM_NUM_CTX", 4096) == 4096


def test_env_int_empty_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_NUM_CTX", "")
    assert _env_int("LLM_NUM_CTX", 4096) == 4096


def test_env_float_unset_returns_default(monkeypatch):
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    assert _env_float("LLM_TEMPERATURE", 0.1) == 0.1


def test_env_float_valid_is_parsed(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
    assert _env_float("LLM_TEMPERATURE", 0.1) == 0.7


def test_env_float_unparseable_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "hot")
    assert _env_float("LLM_TEMPERATURE", 0.1) == 0.1
