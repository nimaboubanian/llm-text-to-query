"""Cloud-model detection and cloud-aware error mapping in the Ollama client."""
import io
import urllib.error

import pytest

from backend.llm import ollama
from backend.llm.ollama import is_cloud_model


def test_is_cloud_model_matches_the_cloud_suffix_only():
    assert is_cloud_model("qwen3-coder:480b-cloud")
    assert is_cloud_model("gpt-oss:120b-cloud")
    assert not is_cloud_model("qwen2.5-coder:7b")
    # A "cloud" that isn't the tag suffix must not count.
    assert not is_cloud_model("cloud-sqlcoder:7b")
    assert not is_cloud_model("mycloud/model:7b")


def test_warmup_skips_cloud_models_without_touching_the_daemon(monkeypatch):
    """Preloading is meaningless remotely and burns quota — it must not be attempted."""
    calls = []

    def _fail(*args, **kwargs):
        calls.append(args)
        return 200, {}

    monkeypatch.setattr(ollama, "_post_json", _fail)
    assert ollama.warmup("qwen3-coder:480b-cloud") is True
    assert calls == []


def test_warmup_still_preloads_local_models(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ollama, "_post_json",
        lambda url, payload, timeout: (calls.append(payload["model"]), (200, {}))[1],
    )
    assert ollama.warmup("qwen2.5-coder:7b") is True
    assert calls == ["qwen2.5-coder:7b"]


@pytest.mark.parametrize("status", [429, 401, 403, 500])
def test_generation_result_records_the_http_status(monkeypatch, status):
    """The runner keys its quota abort off the status code, not off error text."""
    monkeypatch.setattr(ollama, "_post_json", lambda *a, **kw: (status, {}))
    result = ollama.generate_sql("q", "schema", "qwen3-coder:480b-cloud")
    assert result.status_code == status
    assert result.sql is None


def test_429_on_a_cloud_model_reports_a_rate_limit_not_an_exhausted_quota(monkeypatch):
    """At the first 429 we cannot tell a spent usage budget from a concurrency
    rejection — only the runner's probe can. The message must not overclaim."""
    monkeypatch.setattr(ollama, "_post_json", lambda *a, **kw: (429, {}))
    result = ollama.generate_sql("q", "schema", "qwen3-coder:480b-cloud")
    assert "rate limit" in result.error.lower()
    assert "429" in result.error
    assert "exhausted" not in result.error.lower()


def test_the_servers_error_message_survives_into_the_error_string(monkeypatch):
    """{"error": ...} is the only place Ollama Cloud says *why* it refused. Losing it
    leaves the user with a bare status code in the report."""
    monkeypatch.setattr(
        ollama, "_post_json",
        lambda *a, **kw: (429, {"error": "session usage limit reached"}),
    )
    result = ollama.generate_sql("q", "schema", "qwen3-coder:480b-cloud")
    assert "session usage limit reached" in result.error


def _http_error(code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://ollama:11434", code, "err", None, io.BytesIO(body))


def test_post_json_decodes_the_error_body(monkeypatch):
    monkeypatch.setattr(
        ollama.urllib.request, "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(
            _http_error(429, b'{"error": "too many concurrent requests"}')
        ),
    )
    status, data = ollama._post_json("http://ollama:11434/api/generate", {}, 5)
    assert status == 429
    assert data == {"error": "too many concurrent requests"}


@pytest.mark.parametrize("body", [b"", b"<html>gateway timeout</html>", b"null"])
def test_post_json_survives_a_body_it_cannot_decode(monkeypatch, body):
    """An exception while handling an error would replace a useful message with a
    traceback — every malformed body must degrade, not raise."""
    monkeypatch.setattr(
        ollama.urllib.request, "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(_http_error(502, body)),
    )
    status, data = ollama._post_json("http://ollama:11434/api/generate", {}, 5)
    assert status == 502
    assert isinstance(data, dict)


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_on_a_cloud_model_says_ollama_cloud_auth_failed(monkeypatch, status):
    monkeypatch.setattr(ollama, "_post_json", lambda *a, **kw: (status, {}))
    result = ollama.generate_sql("q", "schema", "qwen3-coder:480b-cloud")
    assert "Ollama Cloud auth failed" in result.error
    assert "signin" in result.error


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_on_a_local_model_keeps_the_generic_error(monkeypatch, status):
    """A local 403 is an origins/CORS problem, not a cloud credential problem —
    claiming otherwise would send the user chasing an ollama.com account."""
    monkeypatch.setattr(ollama, "_post_json", lambda *a, **kw: (status, {}))
    result = ollama.generate_sql("q", "schema", "qwen2.5-coder:7b")
    assert result.error == f"LLM API error: {status}"


def test_success_leaves_status_code_none(monkeypatch):
    monkeypatch.setattr(
        ollama, "_post_json",
        lambda *a, **kw: (200, {"response": "SELECT 1;", "total_duration": 2_000_000_000}),
    )
    result = ollama.generate_sql("q", "schema", "qwen2.5-coder:7b")
    assert result.status_code is None
    assert result.sql == "SELECT 1;"
