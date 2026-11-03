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
        def __init__(self, host=None):
            self.host = host
            self.calls = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            return {"message": {"content": "local answer"}}

    created = []
    def fake_gateway(**kwargs):
        gateway = FakeGateway(**kwargs)
        created.append(gateway)
        return gateway
    monkeypatch.setattr("core.llm.ModelGateway", fake_gateway)
    llm = LocalLLM(model="qwen-local", temperature=0.3, host="http://127.0.0.1:11435")
    gateway = created[0]
    assert gateway.host == "http://127.0.0.1:11435"
    result = llm.chat([{"role": "user", "content": "hello"}])
    assert result["message"]["content"] == "local answer"
    assert gateway.calls[0]["model"] == "qwen-local"
    assert gateway.calls[0]["temperature"] == 0.3

def test_gateway_rejects_tool_calling_when_provider_does_not_support_it():
    registry = ProviderRegistry()
    provider = FakeProvider()
    provider.manifest = ProviderManifest(
        provider_id="text-only", display_name="Text only", execution_location="test",
        capabilities=ModelCapabilities(text=True, tool_calling=False),
    )
    registry.register(provider)
    gateway = ModelGateway(registry=registry, provider_id="text-only")
    with pytest.raises(ValueError, match="does not support tool calling"):
        gateway.chat("m", [{"role": "user", "content": "hi"}], tools=[{"type": "function"}])

def test_gateway_rejects_streaming_when_provider_does_not_support_it():
    registry = ProviderRegistry()
    provider = FakeProvider()
    provider.manifest = ProviderManifest(
        provider_id="no-stream", display_name="No stream", execution_location="test",
        capabilities=ModelCapabilities(streaming=False),
    )
    registry.register(provider)
    gateway = ModelGateway(registry=registry, provider_id="no-stream")
    with pytest.raises(ValueError, match="does not support streaming"):
        gateway.chat("m", [{"role": "user", "content": "hi"}], stream=True)

@pytest.mark.parametrize("temperature", [-0.1, 2.1, float("nan")])
def test_gateway_rejects_invalid_temperature(temperature):
    registry = ProviderRegistry()
    registry.register(FakeProvider())
    gateway = ModelGateway(registry=registry, provider_id="fake")
    with pytest.raises(ValueError, match="Temperature must be between"):
        gateway.chat("m", [{"role": "user", "content": "hi"}], temperature=temperature)

def test_gateway_rejects_malformed_messages():
    registry = ProviderRegistry()
    registry.register(FakeProvider())
    gateway = ModelGateway(registry=registry, provider_id="fake")
    with pytest.raises(ValueError, match="supported role and non-empty text"):
        gateway.chat("m", [{"role": "developer", "content": "bad"}])

def test_registry_rejects_provider_without_manifest_or_chat():
    registry = ProviderRegistry()
    with pytest.raises(ValueError, match="valid ProviderManifest"):
        registry.register(object())

def test_remote_model_adapter_preserves_tool_calls_and_usage(monkeypatch):
    from core.model_gateway import OpenAICompatibleModelAdapter
    from core.providers import ProviderConfig

    class FakeRemoteClient:
        def chat_response(self, payload, *, tools=None, temperature=0.4, model=None):
            assert model == "remote-model"
            assert tools and tools[0]["function"]["name"] == "tool_calculate"
            assert payload["messages"][-1]["content"] == "calculate 6 * 7"
            return {
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "tool_calculate", "arguments": '{"expression":"6 * 7"}'},
                    }],
                },
                "prompt_eval_count": 12,
                "eval_count": 3,
            }

    monkeypatch.setattr("core.model_gateway.OpenAICompatibleProvider", lambda config, **kwargs: FakeRemoteClient())
    config = ProviderConfig("openrouter", "https://openrouter.ai/api/v1/chat/completions",
                            "ORACLE_ARC_OPENROUTER_API_KEY", "ORACLE_ARC_OPENROUTER_MODEL",
                            "openai/gpt-4o-mini")
    registry = ProviderRegistry()
    registry.register(OpenAICompatibleModelAdapter(config))
    gateway = ModelGateway(registry=registry, provider_id="openrouter")
    response = gateway.chat("remote-model", [{"role": "user", "content": "calculate 6 * 7"}],
                            tools=[{"type": "function", "function": {
                                "name": "tool_calculate", "parameters": {"type": "object"},
                            }}])
    assert response["message"]["tool_calls"][0]["id"] == "call_123"
    assert response["prompt_eval_count"] == 12
    assert response["eval_count"] == 3
