import time

import pytest

from core.platform_control_plane import PlatformControlPlane
from core.tenant_identity import TenantIdentityStore
from core.tool_grants import ToolGrantStore


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
    # Tests model the separate owner grant plane; application capabilities alone
    # must not silently authorize a tool.
    grants = ToolGrantStore(path)
    for tool_id in ("tool.search", "tool.calendar"):
        grants.grant(identity.tenant_id, identity.application_id, tool_id, "test-owner")
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
    configure(cp, a)
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
    with pytest.raises(PermissionError, match="owner grant"):
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
    claimed = cp.claim_execution("wrk_worker_a", lease_seconds=5, tenant_id=identity.tenant_id, application_id=identity.application_id)
    assert claimed.execution_id == first and claimed.status == "running"
    assert cp.complete_execution(first, "wrk_worker_a", {"answer": "done"})
    assert cp.get_execution(identity, first).status == "succeeded"
    cp.record_usage(identity, first, "input_tokens", 12)
    cp.record_usage(identity, first, "output_tokens", 8)
    assert cp.usage_summary(identity, 0) == {"input_tokens": 12, "output_tokens": 8}


def test_expired_worker_lease_recovers_and_dead_letters(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    eid = cp.submit_execution(identity, "research", "1.0.0", "local-default", {}, max_attempts=2)
    claim = cp.claim_execution("wrk_worker_a", lease_seconds=5)
    assert claim.execution_id == eid
    with cp._session() as db:
        db.execute("UPDATE arc_executions SET lease_expires_at=? WHERE execution_id=?",
                   (int(time.time()) - 1, eid))
    assert cp.recover_expired_leases() == {"requeued": 1, "dead_letter": 0}
    retry = cp.claim_execution("wrk_worker_b", lease_seconds=5, tenant_id=identity.tenant_id, application_id=identity.application_id)
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


def test_idempotency_key_rejects_different_payload(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    first = cp.submit_execution(identity, "research", "1.0.0", "local-default",
                                {"query": "first"}, idempotency_key="same-key")
    with pytest.raises(ValueError, match="different request payload"):
        cp.submit_execution(identity, "research", "1.0.0", "local-default",
                            {"query": "different"}, idempotency_key="same-key")
    assert cp.get_execution(identity, first).input_json == '{"query":"first"}'


def test_worker_heartbeat_extends_only_current_unexpired_lease(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    eid = cp.submit_execution(identity, "research", "1.0.0", "local-default", {})
    claim = cp.claim_execution("wrk_worker_a", lease_seconds=5)
    assert claim.execution_id == eid
    assert cp.heartbeat_execution(eid, "wrk_worker_a", lease_seconds=60)
    assert not cp.heartbeat_execution(eid, "wrk_worker_b", lease_seconds=60)


def test_cancelling_running_execution_fences_late_worker_result(tmp_path):
    _, ids, identity, cp = setup(tmp_path)
    issued = ids.provision("Tenant A", "APP", "principal-cancel",
                           CAPS + ["agent.execution.cancel"])
    identity = ids.authenticate(issued["secret"])
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    eid = cp.submit_execution(identity, "research", "1.0.0", "local-default", {})
    cp.claim_execution("wrk_worker_a", lease_seconds=60, tenant_id=identity.tenant_id, application_id=identity.application_id)
    assert cp.cancel_execution(identity, eid)
    assert not cp.complete_execution(eid, "wrk_worker_a", {"answer": "late"})
    assert not cp.fail_execution(eid, "wrk_worker_a", "late_worker_failure", retryable=False)
    assert cp.get_execution(identity, eid).status == "cancelled"


def test_worker_credentials_are_independent_scoped_and_revocable(tmp_path):
    from core.worker_identity import WorkerIdentityStore
    path, ids, identity, cp = setup(tmp_path)
    workers = WorkerIdentityStore(path)
    worker_id, token = workers.issue(identity.tenant_id, identity.application_id,
                                      ["execution.claim", "execution.complete"], 3600)
    authenticated = workers.authenticate(token)
    assert authenticated.worker_id == worker_id
    assert authenticated.application_id == identity.application_id
    workers.validate(authenticated, "execution.claim")
    with pytest.raises(PermissionError):
        workers.validate(authenticated, "execution.fail")
    assert workers.revoke(worker_id)
    with pytest.raises(PermissionError):
        workers.authenticate(token)


def test_worker_claim_cannot_cross_application_scope(tmp_path):
    from core.worker_identity import WorkerIdentityStore
    path, ids, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    cp.submit_execution(identity, "research", "1.0.0", "local-default", {})
    other = ids.provision("Tenant B", "APP", "principal-b", CAPS)
    other_identity = ids.authenticate(other["secret"])
    workers = WorkerIdentityStore(path)
    worker_id, _ = workers.issue(other_identity.tenant_id, other_identity.application_id,
                                 ["execution.claim"], 3600)
    assert cp.claim_execution(worker_id, 5, other_identity.tenant_id,
                              other_identity.application_id) is None


def test_worker_claim_requires_authenticated_application_scope(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    with pytest.raises(PermissionError, match="application scope"):
        cp.claim_execution("wrk_fake", 5)


def test_execution_persists_classification_and_region_for_runtime(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest(tools=[]))
    eid = cp.submit_execution(identity, "research", "1.0.0", "local-default",
                               {"prompt": "hello"}, classification="private", region="local")
    claim = cp.claim_execution("wrk_test_worker", 30, identity.tenant_id, identity.application_id)
    assert claim.execution_id == eid
    assert claim.classification == "private"
    assert claim.region == "local"
    assert claim.route_id == "local-default"


def test_worker_executes_model_and_commits_usage_atomically(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from core.platform_worker import PlatformWorker
    from core.worker_identity import WorkerIdentityStore
    path, ids, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest(tools=[]))
    eid = cp.submit_execution(identity, "research", "1.0.0", "local-default",
                               {"prompt": "Explain the task"})
    workers = WorkerIdentityStore(path)
    _, token = workers.issue(identity.tenant_id, identity.application_id,
                             ["execution.claim", "execution.heartbeat", "execution.complete"], 3600)

    class FakeGateway:
        def __init__(self, provider_id):
            assert provider_id == "ollama"

        def chat(self, model, messages, temperature):
            assert model == "qwen2.5:7b"
            assert messages[-1]["content"] == "Explain the task"
            return SimpleNamespace(
                message=SimpleNamespace(content="Completed result"),
                prompt_eval_count=17,
                eval_count=9,
            )

    monkeypatch.setattr("core.platform_worker.ModelGateway", FakeGateway)
    worker = PlatformWorker(path, token)
    result = worker.run_once(lease_seconds=30)
    assert result["execution_id"] == eid
    assert result["status"] == "succeeded"
    assert result["usage"] == {"input_tokens": 17, "output_tokens": 9}
    assert cp.get_execution(identity, eid).status == "succeeded"
    assert cp.usage_summary(identity, 0) == {"input_tokens": 17, "output_tokens": 9}


def test_worker_policy_failure_is_not_retried(tmp_path, monkeypatch):
    from core.platform_worker import PlatformWorker
    from core.worker_identity import WorkerIdentityStore
    path, ids, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    eid = cp.submit_execution(identity, "research", "1.0.0", "local-default",
                               {"prompt": "This manifest requests a tool"})
    workers = WorkerIdentityStore(path)
    _, token = workers.issue(identity.tenant_id, identity.application_id,
                             ["execution.claim", "execution.complete"], 3600)
    worker = PlatformWorker(path, token)
    with pytest.raises(PermissionError):
        worker.run_once(lease_seconds=30)
    assert cp.get_execution(identity, eid).status == "failed"


def test_expired_lease_recovery_is_application_scoped(tmp_path):
    path, ids, identity_a, cp = setup(tmp_path)
    configure(cp, identity_a)
    cp.register_agent(identity_a, "research", "1.0.0", manifest())
    execution_a = cp.submit_execution(identity_a, "research", "1.0.0", "local-default", {})
    issued_b = ids.provision("Tenant B", "APP", "principal-b", CAPS)
    identity_b = ids.authenticate(issued_b["secret"])
    configure(cp, identity_b)
    cp.register_agent(identity_b, "research", "1.0.0", manifest())
    execution_b = cp.submit_execution(identity_b, "research", "1.0.0", "local-default", {})
    cp.claim_execution("wrk_a", 5, identity_a.tenant_id, identity_a.application_id)
    cp.claim_execution("wrk_b", 5, identity_b.tenant_id, identity_b.application_id)
    with cp._session() as db:
        db.execute("UPDATE arc_executions SET lease_expires_at=? WHERE execution_id IN (?,?)",
                   (int(time.time()) - 1, execution_a, execution_b))
    assert cp.recover_expired_leases(identity_a.tenant_id, identity_a.application_id) == {
        "requeued": 1, "dead_letter": 0
    }
    with cp._session() as db:
        status_a = db.execute("SELECT status FROM arc_executions WHERE execution_id=?",
                              (execution_a,)).fetchone()["status"]
        status_b = db.execute("SELECT status FROM arc_executions WHERE execution_id=?",
                              (execution_b,)).fetchone()["status"]
    assert status_a == "queued"
    assert status_b == "running"
