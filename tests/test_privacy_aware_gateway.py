import pytest
from core.privacy_aware_gateway import InferencePolicy, PrivacyAwareModelGateway, ProviderPolicyError


class FakeLocal:
    def __init__(self, location="local", region="local"):
        self.location = location
        self.region = region
        self.calls = []

    def provider_manifest(self):
        return {"provider_id": "ollama", "execution_location": self.location, "region": self.region}

    def chat(self, model, messages, **kwargs):
        self.calls.append({"model": model, "messages": messages, **kwargs})
        return {"message": {"content": "local response"}}


class FakeRemote:
    provider_id = "claude"
    configured = True

    def __init__(self):
        self.calls = []

    def chat_response(self, payload, *, model=None, temperature=0.7):
        self.calls.append({"payload": payload, "model": model, "temperature": temperature})
        return {"message": {"role": "assistant", "content": "Claude response"}}


def public_policy(provider="claude", region="unspecified"):
    return InferencePolicy(
        "tenant-a", "app-a", data_classification="public", allow_remote=True,
        allowed_remote_providers=frozenset({provider}),
        allowed_regions=frozenset({region}),
    )


def test_private_data_is_never_sent_to_remote_provider_even_with_allowlist():
    remote = FakeRemote()
    gateway = PrivacyAwareModelGateway(FakeLocal(), {"claude": (remote, None)})
    policy = InferencePolicy(
        "tenant-a", "app-a", data_classification="private", allow_remote=True,
        allowed_remote_providers=frozenset({"claude"}), allowed_regions=frozenset({"unspecified"}),
    )
    with pytest.raises(ProviderPolicyError, match="public data"):
        gateway.chat(policy, "claude-test", [{"role": "user", "content": "private"}], provider_id="claude")
    assert remote.calls == []


def test_claude_remote_route_requires_public_data_and_explicit_region():
    remote = FakeRemote()
    gateway = PrivacyAwareModelGateway(FakeLocal(), {"claude": (remote, None)})
    result = gateway.chat(public_policy(), "claude-test",
                          [{"role": "user", "content": "public information"}], provider_id="claude")
    assert result.content == "Claude response"
    assert result.provider_id == "claude"
    assert result.remote_egress is True
    assert remote.calls[0]["model"] == "claude-test"
    no_region = InferencePolicy("tenant-a", "app-a", data_classification="public",
        allow_remote=True, allowed_remote_providers=frozenset({"claude"}), allowed_regions=frozenset())
    with pytest.raises(ProviderPolicyError, match="public data and an allowed provider region"):
        gateway.chat(no_region, "claude-test", [{"role": "user", "content": "public"}], provider_id="claude")


def test_remote_ollama_is_public_only_and_requires_explicit_unspecified_region():
    gateway = PrivacyAwareModelGateway(FakeLocal(location="remote", region=None), {})
    private = InferencePolicy("tenant-a", "app-a", data_classification="private",
        allow_remote=True, allowed_remote_providers=frozenset({"ollama"}),
        allowed_regions=frozenset({"unspecified"}))
    with pytest.raises(ProviderPolicyError, match="public data"):
        gateway.chat(private, "qwen", [{"role": "user", "content": "private"}])
    public = InferencePolicy("tenant-a", "app-a", data_classification="public",
        allow_remote=True, allowed_remote_providers=frozenset({"ollama"}),
        allowed_regions=frozenset({"unspecified"}))
    result = gateway.chat(public, "qwen", [{"role": "user", "content": "public"}])
    assert result.remote_egress is True
    assert result.provider_id == "ollama"


def test_remote_ollama_does_not_enable_tools_or_streaming():
    gateway = PrivacyAwareModelGateway(FakeLocal(location="remote", region=None), {})
    policy = InferencePolicy("tenant-a", "app-a", data_classification="public",
        allow_remote=True, allowed_remote_providers=frozenset({"ollama"}),
        allowed_regions=frozenset({"unspecified"}))
    with pytest.raises(ProviderPolicyError, match="tool calling and streaming"):
        gateway.chat(policy, "qwen", [{"role": "user", "content": "public"}], tools=[{}])
    with pytest.raises(ProviderPolicyError, match="tool calling and streaming"):
        gateway.chat(policy, "qwen", [{"role": "user", "content": "public"}], stream=True)


def test_local_ollama_remains_available_for_private_data():
    local = FakeLocal()
    gateway = PrivacyAwareModelGateway(local, {})
    policy = InferencePolicy("tenant-a", "app-a", data_classification="private")
    result = gateway.chat(policy, "qwen", [{"role": "user", "content": "private"}])
    assert result.content["message"]["content"] == "local response"
    assert result.remote_egress is False


def test_default_gateway_registers_claude_without_exposing_credentials():
    gateway = PrivacyAwareModelGateway(FakeLocal())
    manifest = gateway.manifests()
    claude = next(item for item in manifest if item["provider_id"] == "claude")
    assert claude["execution_location"] == "remote"
    assert claude["enabled"] is False
