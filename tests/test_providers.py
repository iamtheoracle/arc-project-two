import httpx
import pytest

from core.providers import (
    AnthropicMessagesProvider,
    OpenAICompatibleProvider,
    PROVIDERS,
    ProviderError,
)


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


def test_claude_uses_native_messages_endpoint_and_server_credentials():
    seen = {}
    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-api-key")
        seen["version"] = request.headers.get("anthropic-version")
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "Hello from Claude"}],
            "usage": {"input_tokens": 12, "output_tokens": 5},
        })
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AnthropicMessagesProvider(api_key="claude-server-secret", model="claude-test", client=client)
    result = provider.chat_response({
        "messages": [
            {"role": "system", "content": "Be precise."},
            {"role": "user", "content": "Hello"},
        ]
    })
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["key"] == "claude-server-secret"
    assert seen["version"] == "2023-06-01"
    assert '"system":"Be precise."' in seen["body"]
    assert result["message"]["content"] == "Hello from Claude"
    assert result["prompt_eval_count"] == 12
    assert result["eval_count"] == 5


def test_claude_tool_calls_round_trip_through_normalized_contract():
    seen = {}
    def handler(request):
        import json
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={
            "content": [
                {"type": "text", "text": "I will calculate that."},
                {"type": "tool_use", "id": "toolu_123", "name": "tool_calculate",
                 "input": {"expression": "6 * 7"}},
            ],
            "usage": {"input_tokens": 20, "output_tokens": 8},
        })
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AnthropicMessagesProvider(api_key="key", client=client)
    result = provider.chat_response({
        "messages": [{"role": "user", "content": "Calculate 6 * 7"}]
    }, tools=[{
        "type": "function",
        "function": {
            "name": "tool_calculate",
            "description": "Calculate an expression",
            "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
        },
    }])
    assert seen["body"]["tools"][0]["name"] == "tool_calculate"
    assert result["message"]["tool_calls"][0]["id"] == "toolu_123"
    assert result["message"]["tool_calls"][0]["function"]["name"] == "tool_calculate"
    assert result["message"]["tool_calls"][0]["function"]["arguments"] == '{"expression":"6 * 7"}'


def test_claude_converts_assistant_tool_and_tool_result_history():
    import json
    provider = AnthropicMessagesProvider(api_key="key", client=httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            "content": [{"type": "text", "text": "Done"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }))
    ))
    system, messages = provider._convert_messages([
        {"role": "user", "content": "Calculate"},
        {"role": "assistant", "content": " ", "tool_calls": [{
            "id": "toolu_1", "type": "function",
            "function": {"name": "tool_calculate", "arguments": '{"expression":"6 * 7"}'},
        }]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": '{"result":42}'},
    ])
    assert system == ""
    assert messages[1]["content"][0]["type"] == "tool_use"
    assert messages[2]["content"][0]["tool_use_id"] == "toolu_1"


def test_claude_refuses_missing_credentials():
    provider = AnthropicMessagesProvider(api_key="")
    with pytest.raises(ProviderError, match="credentials"):
        provider.chat_response({"messages": [{"role": "user", "content": "hello"}]})
