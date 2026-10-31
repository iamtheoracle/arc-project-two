import pytest
from core.privacy_gateway import InferencePolicy, PrivacyAwareModelGateway


class FakeLocal:
    def chat(self, *args, **kwargs):
        return {"message":{"content":"local"}}


class FakeRemote:
    def chat(self, payload):
        return "remote"


def test_remote_provider_is_denied_without_explicit_application_policy():
    gateway=PrivacyAwareModelGateway(FakeLocal(),{"groq":FakeRemote()})
    policy=InferencePolicy("tenant-a","app-a",("ollama",),allow_remote=False)
    with pytest.raises(PermissionError):
        gateway.chat(policy,"model",[{"role":"user","content":"private"}],provider_id="groq")


def test_sensitive_context_cannot_leave_local_provider():
    gateway=PrivacyAwareModelGateway(FakeLocal(),{"groq":FakeRemote()})
    policy=InferencePolicy("tenant-a","app-a",("groq",),data_classification="sensitive",
                           allow_remote=True,allowed_regions=("unspecified",))
    with pytest.raises(PermissionError):
        gateway.chat(policy,"model",[{"role":"user","content":"private"}],provider_id="groq")


def test_remote_provider_requires_region_allowance_and_no_tool_or_stream():
    gateway=PrivacyAwareModelGateway(FakeLocal(),{"groq":FakeRemote()})
    policy=InferencePolicy("tenant-a","app-a",("groq",),allow_remote=True,
                           allowed_regions=("unspecified",))
    result=gateway.chat(policy,"model",[{"role":"user","content":"hello"}],provider_id="groq")
    assert result["message"]["content"]=="remote"
    with pytest.raises(PermissionError):
        gateway.chat(policy,"model",[{"role":"user","content":"hello"}],tools=[{}],provider_id="groq")


def test_local_provider_stays_available_when_explicitly_allowlisted():
    gateway=PrivacyAwareModelGateway(FakeLocal(),{})
    policy=InferencePolicy("tenant-a","app-a",("ollama",),allowed_regions=("local",))
    assert gateway.chat(policy,"model",[{"role":"user","content":"hello"}])["message"]["content"]=="local"
