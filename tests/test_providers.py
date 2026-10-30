import httpx
import pytest

from core.providers import OpenAICompatibleProvider, PROVIDERS, ProviderError


def test_provider_uses_server_key_and_parses_chat_response():
    config = PROVIDERS[0]
    seen = {}
    def handler(request):
        seen["authorization"] = request.headers["authorization"]
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hello from provider"}}]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(config, api_key="server-secret", model="test-model", client=client)
    assert provider.chat({"messages": [{"role": "user", "content": "Hello"}]}) == "Hello from provider"
    assert seen["authorization"] == "Bearer server-secret"
    assert '"model":"test-model"' in seen["body"]


def test_provider_refuses_missing_credentials():
    provider = OpenAICompatibleProvider(PROVIDERS[0], api_key="")
    with pytest.raises(ProviderError, match="credentials"):
        provider.chat({"messages": []})


def test_gemini_uses_api_key_header_not_bearer():
    config = next(item for item in PROVIDERS if item.provider_id == "gemini")
    seen = {}
    def handler(request):
        seen.update(dict(request.headers))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Gemini response"}}]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(config, api_key="gemini-secret", client=client)
    assert provider.chat({"messages": []}) == "Gemini response"
    assert seen["x-goog-api-key"] == "gemini-secret"
    assert "authorization" not in seen


def test_provider_hides_remote_error_details():
    config = PROVIDERS[0]
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(401, text="secret provider diagnostic")
    ))
    provider = OpenAICompatibleProvider(config, api_key="key", client=client)
    with pytest.raises(ProviderError) as error:
        provider.chat({"messages": []})
    assert "secret provider diagnostic" not in str(error.value)
