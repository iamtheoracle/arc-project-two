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

def test_remote_ollama_is_rejected_without_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.internal:11434")
    monkeypatch.delenv("ORACLE_ARC_ALLOW_REMOTE_OLLAMA", raising=False)
    with pytest.raises(ValueError, match="Remote Ollama is disabled"):
        LocalLLM()

def test_remote_ollama_requires_https_even_with_opt_in(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.example.com:11434")
    monkeypatch.setenv("ORACLE_ARC_ALLOW_REMOTE_OLLAMA", "true")
    with pytest.raises(ValueError, match="must use HTTPS"):
        LocalLLM()

def test_remote_ollama_manifest_discloses_remote_execution(monkeypatch):
    captured = {}
    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
    monkeypatch.setattr("core.model_gateway.ollama.Client", FakeClient)
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.example.com:11434")
    monkeypatch.setenv("ORACLE_ARC_ALLOW_REMOTE_OLLAMA", "true")
    manifest = LocalLLM().gateway.provider_manifest()
    assert manifest["execution_location"] == "remote"
    assert manifest["display_name"] == "Ollama (remote)"
    assert captured["host"].startswith("https://")

@pytest.mark.parametrize("host", ["file:///tmp/ollama", "http://user:pass@localhost:11434", "not-a-url"])
def test_ollama_host_rejects_unsafe_url_forms(monkeypatch, host):
    monkeypatch.setenv("OLLAMA_HOST", host)
    with pytest.raises(ValueError, match="valid HTTP(S) URL"):
        LocalLLM()