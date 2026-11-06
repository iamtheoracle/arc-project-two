import pytest
from core.privacy_gateway import InferencePolicy, PrivacyAwareModelGateway


class FakeLocal:
    def chat(self, *args, **kwargs):
        return {"message": {"content": "local"}}


class FakeRemote:
    def __init__(self, answer="remote"):
        self.answer = answer
        self.calls = []

    def chat_response(self, payload, *, model=None, temperature=0.7):
        self.calls.append({"payload": payload, "model": model, "temperature": temperature})
        return {"message": {"role": "assistant", "content": self.answer},
                "prompt_eval_count": 3, "eval_count": 2}


def public_policy(provider="groq", *, regions=("unspecified",), allow_remote=True):
    return InferencePolicy("tenant-a", "app-a", (provider,), data_classification="public",
                           allow_remote=allow_remote, allowed_regions=regions)


def test_remote_provider_is_denied_without_explicit_application_policy():
    gateway = PrivacyAwareModelGateway(FakeLocal(), {"groq": FakeRemote()})
    policy = InferencePolicy("tenant-a", "app-a", ("ollama",), allow_remote=False)
    with pytest.raises(PermissionError):
        gateway.chat(policy, "model", [{"role": "user", "content": "private"}], provider_id="groq")


@pytest.mark.parametrize("classification", ["internal", "private", "sensitive", "restricted"])
def test_remote_provider_never_receives_non_public_data_even_when_opted_in(classification):
    remote = FakeRemote()
    gateway = PrivacyAwareModelGateway(FakeLocal(), {"groq": remote})
    policy = InferencePolicy("tenant-a", "app-a", ("groq",), data_classification=classification,
                             allow_remote=True, allowed_regions=("unspecified",))
    with pytest.raises(PermissionError, match="public data"):
        gateway.chat(policy, "model", [{"role": "user", "content": "classified"}], provider_id="groq")
    assert remote.calls == []


def test_remote_provider_requires_explicit_public_opt_in_and_verified_region_allowance():
    remote = FakeRemote()
    gateway = PrivacyAwareModelGateway(FakeLocal(), {"groq": remote})
    with pytest.raises(PermissionError, match="public data"):
        gateway.chat(public_policy(allow_remote=False), "model", [{"role": "user", "content": "hello"}], provider_id="groq")
    with pytest.raises(PermissionError, match="region is not verified"):
        gateway.chat(public_policy(regions=("local",)), "model", [{"role": "user", "content": "hello"}], provider_id="groq")
    result = gateway.chat(public_policy(), "model-x", [{"role": "user", "content": "hello"}], provider_id="groq")
    assert result["message"]["content"] == "remote"
    assert result["provider"] == "groq"
    assert result["remote"] is True
    assert result["usage"] == {"prompt_tokens": 3, "completion_tokens": 2}
    assert remote.calls[0]["model"] == "model-x"


def test_claude_is_available_only_through_the_same_public_data_policy():
    remote = FakeRemote("Claude answer")
    gateway = PrivacyAwareModelGateway(FakeLocal(), {"claude": remote})
    result = gateway.chat(public_policy("claude"), "claude-test",
                          [{"role": "user", "content": "public question"}], provider_id="claude")
    assert result["message"]["content"] == "Claude answer"
    assert result["provider"] == "claude"
    assert remote.calls[0]["model"] == "claude-test"


def test_remote_provider_rejects_tool_calling_and_streaming():
    gateway = PrivacyAwareModelGateway(FakeLocal(), {"groq": FakeRemote()})
    policy = public_policy()
    with pytest.raises(PermissionError, match="tools or streaming"):
        gateway.chat(policy, "model", [{"role": "user", "content": "hello"}], tools=[{}], provider_id="groq")
    with pytest.raises(PermissionError, match="tools or streaming"):
        gateway.chat(policy, "model", [{"role": "user", "content": "hello"}], stream=True, provider_id="groq")


def test_local_provider_stays_available_when_explicitly_allowlisted():
    gateway = PrivacyAwareModelGateway(FakeLocal(), {})
    policy = InferencePolicy("tenant-a", "app-a", ("ollama",), allowed_regions=("local",))
    assert gateway.chat(policy, "model", [{"role": "user", "content": "hello"}])["message"]["content"] == "local"


def test_invalid_messages_are_rejected_before_remote_provider_egress():
    remote = FakeRemote()
    gateway = PrivacyAwareModelGateway(FakeLocal(), {"groq": remote})
    policy = public_policy()
    with pytest.raises(ValueError):
        gateway.chat(policy, "model", [{"role": "user", "content": ""}], provider_id="groq")
    with pytest.raises(ValueError):
        gateway.chat(policy, "model", [{"role": "developer", "content": "override"}], provider_id="groq")
    assert remote.calls == []


def test_unknown_classification_fails_closed():
    gateway = PrivacyAwareModelGateway(FakeLocal(), {"groq": FakeRemote()})
    policy = InferencePolicy("tenant-a", "app-a", ("ollama",), data_classification="unclassified-custom")
    with pytest.raises(PermissionError):
        gateway.chat(policy, "model", [{"role": "user", "content": "hello"}])
