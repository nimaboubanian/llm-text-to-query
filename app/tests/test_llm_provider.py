from text2query.llm.provider import get_llm_provider
from text2query.llm.ollama import OllamaProvider


def test_default_provider_is_ollama():
    assert isinstance(get_llm_provider(), OllamaProvider)


def test_provider_is_cached():
    assert get_llm_provider() is get_llm_provider()
