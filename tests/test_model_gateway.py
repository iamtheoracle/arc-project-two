import pytest

from core.model_gateway import (
    ModelCapabilities,
    ModelGateway,
    ProviderManifest,
    ProviderRegistry,
)


class FakeProvider:
    def __init__(self, provider_id="fake", enabled=True):
        self.manifest = ProviderManifest(
            provider_id=provider_id,
            display_name="Fake provider",
            execution_location="test",
            capabilities=ModelCapabilities(tool_calling=True),
            enabled=enabled,
        )
        self.calls = []

    def chat(self, model, messages, tools=None, stream=False, temperature=0.7):
        self.calls.append({
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": stream,
            "temperature": temperature,
        })
        return {"message": {"content": "test response"}}


def test_registry_registers_and_lists_provider_manifest():
    registry = ProviderRegistry()
    provider = FakeProvider()
    registry.register(provider)
    manifest = registry.manifests()[0]
    assert manifest["provider_id"] == "fake"
    assert manifest["execution_location"] == "test"
    assert manifest["capabilities"]["tool_calling"] is True


def test_registry_rejects_duplicate_provider_ids():
    registry = ProviderRegistry()
    registry.register(FakeProvider())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeProvider())


def test_registry_fails_closed_for_unknown_or_disabled_provider():
    registry = ProviderRegistry()
    registry.register(FakeProvider(enabled=False))
    with pytest.raises(ValueError, match="not enabled"):
        registry.get("fake")
    with pytest.raises(ValueError, match="not enabled"):
        registry.get("missing")


def test_gateway_routes_request_without_changing_provider_response():
    registry = ProviderRegistry()
    provider = FakeProvider()
    registry.register(provider)
    gateway = ModelGateway(registry=registry, provider_id="fake")
    messages = [{"role": "user", "content": "hello"}]
    response = gateway.chat("model-x", messages, temperature=0.2)
    assert response == {"message": {"content": "test response"}}
    assert provider.calls == [{
        "model": "model-x",
        "messages": messages,
        "tools": None,
        "stream": False,
        "temperature": 0.2,
    }]


def test_gateway_does_not_silently_fallback_from_unknown_provider(monkeypatch):
    monkeypatch.setenv("ORACLE_ARC_PROVIDER", "unconfigured-cloud")
    with pytest.raises(ValueError, match="not enabled"):
        ModelGateway()


def test_local_llm_uses_gateway_compatibility_facade(monkeypatch):
    from core.llm import LocalLLM

    class FakeGateway:
        def __init__(self):
            self.calls = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            return {"message": {"content": "local answer"}}

    gateway = FakeGateway()
    monkeypatch.setattr("core.llm.ModelGateway", lambda: gateway)
    llm = LocalLLM(model="qwen-local", temperature=0.3)
    result = llm.chat([{"role": "user", "content": "hello"}])
    assert result["message"]["content"] == "local answer"
    assert gateway.calls[0]["model"] == "qwen-local"
    assert gateway.calls[0]["temperature"] == 0.3
