import httpx
import pytest

from core.model_discovery import DiscoveryError, LocalOllamaDiscovery


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_loopback_discovery_and_capabilities_are_provider_reported():
    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.5.1"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": "vision-model:latest", "digest": "abc", "size": 123}
            ]})
        assert request.url.path == "/api/show"
        return httpx.Response(200, json={"capabilities": ["completion", "vision", "tools"]})

    discovery = LocalOllamaDiscovery(client=client_for(handler))
    assert discovery.health().status == "ready"
    model = discovery.discover()[0]
    assert model.model_id == "vision-model:latest"
    assert model.capabilities.text is True
    assert model.capabilities.vision is True
    assert model.capabilities.tool_calling is True
    assert model.capabilities.embeddings is False
    assert model.capabilities.streaming is False
    assert model.capability_source == "ollama_api_show"


def test_unknown_capabilities_fail_closed():
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "m"}]})
        return httpx.Response(200, json={"details": {"family": "llama"}})

    model = LocalOllamaDiscovery(client=client_for(handler)).discover()[0]
    assert not model.capabilities.text
    assert not model.capabilities.vision
    assert model.capability_source == "unknown"


@pytest.mark.parametrize("host", [
    "https://models.example.com", "http://192.168.1.10:11434",
    "http://127.0.0.1:11434/private", "http://user:pass@localhost:11434",
])
def test_discovery_rejects_non_loopback_or_ambiguous_hosts(host):
    with pytest.raises(ValueError):
        LocalOllamaDiscovery(host=host)


def test_health_rejects_malformed_version():
    discovery = LocalOllamaDiscovery(client=client_for(
        lambda request: httpx.Response(200, json={"version": 17})))
    with pytest.raises(DiscoveryError):
        discovery.health()


def test_discovery_rejects_invalid_limits():
    discovery = LocalOllamaDiscovery(client=client_for(
        lambda request: httpx.Response(200, json={"models": []})))
    with pytest.raises(ValueError):
        discovery.discover(0)


def test_discovery_does_not_leak_http_errors():
    discovery = LocalOllamaDiscovery(client=client_for(
        lambda request: httpx.Response(503, text="secret backend detail")))
    with pytest.raises(DiscoveryError, match="unavailable"):
        discovery.health()
