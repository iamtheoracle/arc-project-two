import pytest

from core.llm import LocalLLM


def test_local_llm_passes_configured_timeout_and_host_to_ollama(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("core.model_gateway.ollama.Client", FakeClient, raising=False)
    monkeypatch.setenv("ORACLE_ARC_OLLAMA_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    llm = LocalLLM(model="qwen2.5:7b")
    assert captured["timeout"] == 45
    assert captured["host"] == "http://127.0.0.1:11434"
    assert llm.gateway.provider_manifest()["provider_id"] == "ollama"


@pytest.mark.parametrize("value", ["0", "-1", "901"])
def test_local_llm_rejects_unsafe_timeout_configuration(monkeypatch, value):
    monkeypatch.setenv("ORACLE_ARC_OLLAMA_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError):
        LocalLLM()
