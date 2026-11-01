import pytest

from core.model_gateway import OllamaProvider
from core.providers import OpenAICompatibleProvider, ProviderConfig


def test_ollama_provider_uses_bounded_configured_client_timeout(monkeypatch):
    import core.model_gateway as gateway_module

    captured = {}

    class FakeOllamaClient:
        def __init__(self, host, timeout):
            captured["host"] = host
            captured["timeout"] = timeout

    monkeypatch.setattr(gateway_module.ollama, "Client", FakeOllamaClient)
    monkeypatch.setenv("ORACLE_ARC_OLLAMA_TIMEOUT_SECONDS", "17")
    provider = OllamaProvider()
    assert captured["host"] == "http://127.0.0.1:11434"
    assert captured["timeout"] == 17
    assert provider.manifest.execution_location == "local"


def test_ollama_provider_rejects_unbounded_timeout(monkeypatch):
    monkeypatch.setenv("ORACLE_ARC_OLLAMA_TIMEOUT_SECONDS", "901")
    with pytest.raises(ValueError, match="between 0 and 900"):
        OllamaProvider()


def test_remote_provider_passes_explicit_timeout_to_http_client():
    config = ProviderConfig(
        provider_id="test-provider",
        endpoint="https://provider.example.test/chat",
        api_key_env="TEST_PROVIDER_KEY",
        model_env="TEST_PROVIDER_MODEL",
        default_model="test-model",
    )
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            }

    class FakeHttpClient:
        def post(self, endpoint, *, headers, json, timeout):
            captured.update({"endpoint": endpoint, "timeout": timeout})
            return Response()

    provider = OpenAICompatibleProvider(
        config, api_key="test-secret", timeout_seconds=4.5,
        client=FakeHttpClient(),
    )
    result = provider.chat_response({"messages": [{"role": "user", "content": "hello"}]})
    assert captured["endpoint"] == config.endpoint
    assert captured["timeout"] == 4.5
    assert result["message"]["content"] == "ok"



def test_ollama_timeout_can_be_tightened_between_worker_rounds(monkeypatch):
    import core.model_gateway as gateway_module

    seen = []

    class FakeOllamaClient:
        def __init__(self, host, timeout):
            seen.append(timeout)

    monkeypatch.setattr(gateway_module.ollama, "Client", FakeOllamaClient)
    provider = OllamaProvider(timeout_seconds=30)
    provider.set_timeout_seconds(2.25)
    assert seen == [30, 2.25]
