from types import SimpleNamespace

from core.tenant_api import InferenceRequest, build_inference_policy


def identity(*capabilities):
    return SimpleNamespace(tenant_id="tenant-a", application_id="app-a",
                           capabilities=tuple(capabilities), policy_version=7)


def test_private_remote_capability_cannot_enable_cloud_inference():
    policy = build_inference_policy(identity(
        "inference.chat", "inference.provider.ollama", "inference.remote.allow",
        "inference.remote.private", "inference.remote.region.unspecified", "inference.remote.claude",
    ))
    assert policy.data_classification == "private"
    assert policy.allow_remote is False
    assert policy.allowed_providers == ("ollama",)


def test_remote_inference_requires_public_capability_and_provider_specific_grant():
    policy = build_inference_policy(identity(
        "inference.chat", "inference.provider.ollama", "inference.remote.allow",
        "inference.remote.public", "inference.remote.region.unspecified", "inference.remote.claude",
    ))
    assert policy.data_classification == "public"
    assert policy.allow_remote is True
    assert policy.allowed_providers == ("ollama", "claude")
    assert policy.allowed_regions == ("local", "unspecified")
    assert policy.policy_version == 7


def test_request_body_cannot_set_its_own_data_classification():
    assert "data_classification" not in InferenceRequest.model_fields
