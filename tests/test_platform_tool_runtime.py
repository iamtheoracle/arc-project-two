import json

import pytest

from core.platform_runtime import default_runtime_registry


def test_local_ollama_runtime_executes_only_authorized_installed_tool(monkeypatch):
    import core.model_gateway as gateway_module

    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    calls = []

    class FakeGateway:
        def __init__(self, provider_id=None):
            assert provider_id == "ollama"

        def chat(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return {
                    "message": {
                        "content": "",
                        "tool_calls": [{
                            "function": {
                                "name": "math.calculate",
                                "arguments": {"expression": "(4 + 6) * 3"},
                            }
                        }],
                    },
                    "prompt_eval_count": 11,
                    "eval_count": 2,
                }
            assert kwargs["messages"][-1]["role"] == "tool"
            assert json.loads(kwargs["messages"][-1]["content"]) == {"result": 30}
            return {
                "message": {"content": "The answer is 30.", "tool_calls": []},
                "prompt_eval_count": 7,
                "eval_count": 5,
            }

    monkeypatch.setattr(gateway_module, "ModelGateway", FakeGateway)
    authorized = []
    result = default_runtime_registry().execute(
        "oracle-arc-agent-v1",
        {
            "model_provider": "ollama",
            "model_id": "qwen2.5:7b",
            "classification": "private",
            "input_json": json.dumps({
                "messages": [{"role": "user", "content": "What is (4 + 6) * 3?"}],
                "temperature": 0.2,
            }),
        },
        {"runtime": "oracle-arc-agent-v1", "allowed_tools": ["math.calculate"]},
        tool_authorizer=lambda tool_id: authorized.append(tool_id) or True,
    )
    assert result == {
        "answer": "The answer is 30.",
        "input_tokens": 18,
        "output_tokens": 7,
    }
    assert authorized == ["math.calculate"]
    assert len(calls) == 2
    assert calls[0]["tools"][0]["function"]["name"] == "math.calculate"


def test_local_ollama_runtime_stops_when_live_tool_authorization_denies(monkeypatch):
    import core.model_gateway as gateway_module
    from core.platform_runtime import default_runtime_registry

    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")

    class FakeGateway:
        def __init__(self, provider_id=None):
            pass

        def chat(self, **kwargs):
            return {"message": {"content": "", "tool_calls": [{
                "function": {"name": "math.calculate", "arguments": {"expression": "1+1"}}
            }]}}

    monkeypatch.setattr(gateway_module, "ModelGateway", FakeGateway)
    with pytest.raises(PermissionError, match="live execution policy"):
        default_runtime_registry().execute(
            "oracle-arc-agent-v1",
            {"model_provider": "ollama", "model_id": "qwen2.5:7b",
             "classification": "private",
             "input_json": '{"messages":[{"role":"user","content":"calculate"}]}'},
            {"runtime": "oracle-arc-agent-v1", "allowed_tools": ["math.calculate"]},
            tool_authorizer=lambda tool_id: False,
        )
