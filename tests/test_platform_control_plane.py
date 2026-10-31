import time

import pytest

from core.platform_control_plane import PlatformControlPlane
from core.tenant_identity import TenantIdentityStore


CAPS = [
    "agent.register", "agent.read", "agent.manage", "agent.execute",
    "agent.execution.read", "model.route.manage", "model.route.use",
    "quota.manage", "usage.write", "usage.read", "reasoning",
    "tool.search", "tool.calendar",
]


def setup(tmp_path, name="Tenant A", app="APP"):
    path = str(tmp_path / "platform.sqlite3")
    identities = TenantIdentityStore(path)
    issued = identities.provision(name, app, "principal-" + name.lower().replace(" ", "-"), CAPS)
    identity = identities.authenticate(issued["secret"])
    return path, identities, identity, PlatformControlPlane(path)


def manifest(tools=None):
    return {
        "display_name": "Research agent",
        "description": "Tenant-scoped research specialist",
        "required_capabilities": ["reasoning"],
        "allowed_tools": tools or ["tool.search"],
        "model_routes": ["local-default"],
        "runtime": "oracle-arc-agent-v1",
    }


def configure(cp, identity):
    cp.configure_model_route(identity, "local-default", "ollama", "qwen2.5:7b",
                              ["public", "internal", "private"], ["local"])
    cp.set_quota(identity, window_seconds=60, max_executions=5,
                 max_concurrent=2, max_input_bytes=2048)


def test_agent_versions_are_immutable_and_application_scoped(tmp_path):
    path, ids, a, cp = setup(tmp_path)
    _, _, b, _ = setup(tmp_path, "Tenant B", "APP")
    cp.register_agent(a, "research", "1.0.0", manifest())
    cp.register_agent(a, "research", "1.1.0", manifest(["tool.search", "tool.calendar"]))
    assert cp.get_agent(a, "research", "1.0.0").manifest["allowed_tools"] == ["tool.search"]
    with pytest.raises(LookupError):
        cp.get_agent(b, "research")
    with pytest.raises(Exception):
        cp.register_agent(a, "research", "1.0.0", manifest())


def test_agent_manifest_cannot_grant_its_own_tools(tmp_path):
    path, ids, identity, cp = setup(tmp_path)
    bad = manifest(["admin.root"])
    with pytest.raises(PermissionError, match="tool grants"):
        configure(cp, identity)
        cp.register_agent(identity, "research", "1.0.0", bad)
        cp.submit_execution(identity, "research", "1.0.0", "local-default", {})


def test_model_routes_enforce_classification_and_region(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    cp.configure_model_route(identity, "local-default", "ollama", "qwen2.5:7b",
                              ["public", "private"], ["local"])
    assert cp.resolve_model_route(identity, "local-default", "private", "local")["model_id"] == "qwen2.5:7b"
    with pytest.raises(PermissionError):
        cp.resolve_model_route(identity, "local-default", "restricted", "local")
    with pytest.raises(PermissionError):
        cp.resolve_model_route(identity, "local-default", "private", "remote")


def test_quota_idempotency_usage_and_execution_lifecycle(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    first = cp.submit_execution(identity, "research", "1.0.0", "local-default",
                                 {"query": "hello"}, idempotency_key="request-1")
    assert cp.submit_execution(identity, "research", "1.0.0", "local-default",
                               {"query": "hello"}, idempotency_key="request-1") == first
    claimed = cp.claim_execution("worker-a", lease_seconds=5)
    assert claimed.execution_id == first and claimed.status == "running"
    assert cp.complete_execution(first, "worker-a", {"answer": "done"})
    assert cp.get_execution(identity, first).status == "succeeded"
    cp.record_usage(identity, first, "input_tokens", 12)
    cp.record_usage(identity, first, "output_tokens", 8)
    assert cp.usage_summary(identity, 0) == {"input_tokens": 12, "output_tokens": 8}


def test_expired_worker_lease_recovers_and_dead_letters(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    eid = cp.submit_execution(identity, "research", "1.0.0", "local-default", {}, max_attempts=2)
    claim = cp.claim_execution("worker-a", lease_seconds=5)
    assert claim.execution_id == eid
    with cp._session() as db:
        db.execute("UPDATE arc_executions SET lease_expires_at=? WHERE execution_id=?",
                   (int(time.time()) - 1, eid))
    assert cp.recover_expired_leases() == {"requeued": 1, "dead_letter": 0}
    retry = cp.claim_execution("worker-b", lease_seconds=5)
    assert retry.attempt == 2
    with cp._session() as db:
        db.execute("UPDATE arc_executions SET lease_expires_at=? WHERE execution_id=?",
                   (int(time.time()) - 1, eid))
    assert cp.recover_expired_leases() == {"requeued": 0, "dead_letter": 1}


def test_quota_is_enforced_before_queueing(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    cp.configure_model_route(identity, "local-default", "ollama", "qwen2.5:7b",
                             ["private"], ["local"])
    cp.set_quota(identity, window_seconds=3600, max_executions=1,
                 max_concurrent=1, max_input_bytes=50)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    cp.submit_execution(identity, "research", "1.0.0", "local-default", {})
    with pytest.raises(PermissionError, match="quota"):
        cp.submit_execution(identity, "research", "1.0.0", "local-default", {})


def test_execution_visibility_and_usage_are_app_scoped(tmp_path):
    path, ids, a, cp = setup(tmp_path)
    issued_b = ids.provision("Tenant B", "APP", "principal-b", CAPS)
    b = ids.authenticate(issued_b["secret"])
    configure(cp, a)
    cp.register_agent(a, "research", "1.0.0", manifest())
    eid = cp.submit_execution(a, "research", "1.0.0", "local-default", {})
    with pytest.raises(LookupError):
        cp.get_execution(b, eid)
    with pytest.raises(LookupError):
        cp.record_usage(b, eid, "tokens", 10)
