import time

import pytest

from core.platform_control_plane import PlatformControlPlane
from core.tenant_identity import TenantIdentityStore


CAPS = [
    "agent.register", "agent.read", "agent.manage", "agent.execute",
    "agent.execution.read", "model.route.manage", "model.route.use",
    "quota.manage", "usage.write", "usage.read", "reasoning",
    "tool.search", "tool.calendar", "worker.register", "worker.manage",
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
    with cp._session() as db:
        db.execute("UPDATE arc_executions SET available_at=? WHERE execution_id=?",
                   (int(time.time()) - 1, eid))
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


def test_idempotency_key_rejects_different_payload(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    first = cp.submit_execution(identity, "research", "1.0.0", "local-default",
                                {"query": "first"}, idempotency_key="same-key")
    with pytest.raises(ValueError, match="different request payload"):
        cp.submit_execution(identity, "research", "1.0.0", "local-default",
                            {"query": "different"}, idempotency_key="same-key")
    with pytest.raises(ValueError, match="different request payload"):
        cp.submit_execution(identity, "research", "1.0.0", "local-default",
                            {"query": "first"}, max_attempts=2, idempotency_key="same-key")
    assert cp.get_execution(identity, first).input_json == '{"query":"first"}'


def test_worker_heartbeat_extends_only_current_unexpired_lease(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    eid = cp.submit_execution(identity, "research", "1.0.0", "local-default", {})
    claim = cp.claim_execution("worker-a", lease_seconds=5)
    assert claim.execution_id == eid
    assert cp.heartbeat_execution(eid, "worker-a", lease_seconds=60)
    assert not cp.heartbeat_execution(eid, "worker-b", lease_seconds=60)


def test_cancelling_running_execution_fences_late_worker_result(tmp_path):
    _, ids, identity, cp = setup(tmp_path)
    issued = ids.provision("Tenant A", "APP", "principal-cancel",
                           CAPS + ["agent.execution.cancel"])
    identity = ids.authenticate(issued["secret"])
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    eid = cp.submit_execution(identity, "research", "1.0.0", "local-default", {})
    cp.claim_execution("worker-a", lease_seconds=60)
    assert cp.cancel_execution(identity, eid)
    assert not cp.complete_execution(eid, "worker-a", {"answer": "late"})
    assert cp.get_execution(identity, eid).status == "cancelled"



def test_worker_credentials_are_independent_scoped_and_revocable(tmp_path):
    from core.platform_workers import WorkerService

    path, _, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    workers = WorkerService(path)
    issued = workers.register(identity, ["oracle-arc-agent-v1"], ttl_seconds=3600)
    worker = workers.authenticate(issued["credential"])
    assert worker.worker_id == issued["worker_id"]
    assert workers.authenticate_from_identity(worker).application_id == identity.application_id

    execution_id = cp.submit_execution(identity, "research", "1.0.0", "local-default", {})
    claim = workers.claim(worker, lease_seconds=5)
    assert claim["execution_id"] == execution_id
    assert "lease_owner" not in claim
    assert "credential_id" not in claim
    assert "policy_version" not in claim
    assert claim["route_id"] == "local-default"
    assert workers.heartbeat(worker, execution_id, 60)
    assert workers.record_usage(worker, execution_id, "evt-1", "input_tokens", 15)
    assert not workers.record_usage(worker, execution_id, "evt-1", "input_tokens", 15)
    with pytest.raises(ValueError, match="different values"):
        workers.record_usage(worker, execution_id, "evt-1", "input_tokens", 16)
    assert workers.complete(worker, execution_id, {"answer": "done"})
    assert cp.get_execution(identity, execution_id).status == "succeeded"

    assert workers.revoke(identity, worker.worker_id)
    with pytest.raises(PermissionError, match="revoked"):
        workers.authenticate(issued["credential"])
    with pytest.raises(PermissionError, match="revoked"):
        workers.heartbeat(worker, execution_id, 60)


def test_worker_cannot_claim_another_application_or_unapproved_runtime(tmp_path):
    from core.platform_workers import WorkerService

    path, ids, identity_a, cp = setup(tmp_path)
    configure(cp, identity_a)
    cp.register_agent(identity_a, "research", "1.0.0", manifest())
    issued_b = ids.provision("Tenant B", "APP", "principal-b", CAPS)
    identity_b = ids.authenticate(issued_b["secret"])
    configure(cp, identity_b)
    cp.register_agent(identity_b, "research", "1.0.0", manifest())
    workers = WorkerService(path)
    worker_b = workers.register(identity_b, ["oracle-arc-agent-v1"])["credential"]
    execution_id = cp.submit_execution(identity_a, "research", "1.0.0", "local-default", {})
    assert workers.claim(workers.authenticate(worker_b), 5) is None
    with pytest.raises(PermissionError, match="server-side trusted runtime allowlist"):
        workers.register(identity_b, ["untrusted-runtime"])


def test_worker_lease_cannot_complete_after_expiry_or_cancellation(tmp_path):
    from core.platform_workers import WorkerService

    path, ids, identity, cp = setup(tmp_path)
    identity_caps = list(identity.capabilities) + ["agent.execution.cancel"]
    # Issue a distinct principal and app in the same durable identity database.
    issued = ids.provision("Tenant A expiry", "APP expiry", "principal-expiry", identity_caps)
    identity = ids.authenticate(issued["secret"])
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    workers = WorkerService(path)
    worker = workers.authenticate(workers.register(identity, ["oracle-arc-agent-v1"])["credential"])
    execution_id = cp.submit_execution(identity, "research", "1.0.0", "local-default", {})
    workers.claim(worker, 5)
    with cp._session() as db:
        db.execute("UPDATE arc_executions SET lease_expires_at=? WHERE execution_id=?",
                   (int(time.time()) - 1, execution_id))
    assert not workers.complete(worker, execution_id, {"late": True})



def test_revoked_submitter_credential_fences_queued_execution(tmp_path):
    from core.platform_workers import WorkerService

    path, _, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    execution_id = cp.submit_execution(identity, "research", "1.0.0", "local-default", {})
    workers = WorkerService(path)
    worker = workers.authenticate(workers.register(identity, ["oracle-arc-agent-v1"])["credential"])
    with cp._session() as db:
        db.execute("UPDATE arc_credentials SET revoked_at=? WHERE credential_id=?",
                   (int(time.time()), identity.credential_id))
    assert workers.claim(worker, 5) is None
    assert cp.get_execution(identity, execution_id).status == "failed"
    assert cp.get_execution(identity, execution_id).error_code == "execution_policy_rejected"



def test_model_route_change_after_submission_fences_execution(tmp_path):
    from core.platform_workers import WorkerService

    path, _, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    execution_id = cp.submit_execution(identity, "research", "1.0.0", "local-default", {})
    workers = WorkerService(path)
    worker = workers.authenticate(workers.register(identity, ["oracle-arc-agent-v1"])["credential"])
    cp.configure_model_route(identity, "local-default", "ollama", "different-model",
                              ["public", "internal", "private"], ["local"])
    assert workers.claim(worker, 5) is None
    execution = cp.get_execution(identity, execution_id)
    assert execution.status == "failed"
    assert execution.error_code == "execution_policy_rejected"


def test_trusted_runtime_dispatch_rejects_uninstalled_and_tool_enabled_runtimes(monkeypatch):
    import pytest
    from core.platform_runtime import (
        RuntimeUnavailable, TrustedRuntimeRegistry, default_runtime_registry,
    )

    registry = TrustedRuntimeRegistry()
    registry.register("unit-test-runtime", lambda execution, manifest: {"ok": True})
    assert registry.execute("unit-test-runtime", {}, {"runtime": "unit-test-runtime"}) == {"ok": True}
    with pytest.raises(RuntimeUnavailable):
        registry.execute("not-installed", {}, {"runtime": "not-installed"})

    default = default_runtime_registry()
    with pytest.raises(RuntimeUnavailable, match="tool adapters"):
        default.execute("oracle-arc-agent-v1",
                        {"model_provider": "ollama", "input_json": '{"messages":[{"role":"user","content":"hi"}]}'},
                        {"runtime": "oracle-arc-agent-v1", "allowed_tools": ["tool.search"]})


def test_first_runtime_refuses_remote_ollama_egress(monkeypatch):
    import pytest
    from core.platform_runtime import RuntimeUnavailable, default_runtime_registry

    monkeypatch.setenv("OLLAMA_HOST", "https://remote.example")
    with pytest.raises(RuntimeUnavailable, match="local Ollama only"):
        default_runtime_registry().execute(
            "oracle-arc-agent-v1",
            {"model_provider": "ollama",
             "input_json": '{"messages":[{"role":"user","content":"hello"}]}'},
            {"runtime": "oracle-arc-agent-v1", "allowed_tools": []})



def test_worker_runner_executes_installed_handler_and_records_usage(tmp_path):
    from core.platform_workers import WorkerService
    from core.platform_worker_runner import run_once

    path, _, identity, cp = setup(tmp_path)
    configure(cp, identity)
    cp.register_agent(identity, "research", "1.0.0", manifest())
    workers = WorkerService(path)
    worker = workers.authenticate(workers.register(identity, ["oracle-arc-agent-v1"])["credential"])
    execution_id = cp.submit_execution(identity, "research", "1.0.0", "local-default", {})

    class FakeRuntimeRegistry:
        def execute(self, runtime_id, execution, agent_manifest):
            assert runtime_id == "oracle-arc-agent-v1"
            assert execution["execution_id"] == execution_id
            return {"answer": "runtime completed", "input_tokens": 7, "output_tokens": 3}

    assert run_once(workers, worker, FakeRuntimeRegistry(), lease_seconds=5)
    result = cp.get_execution(identity, execution_id)
    assert result.status == "succeeded"
    assert '"answer":"runtime completed"' in result.output_json
    assert cp.usage_summary(identity, 0) == {"input_tokens": 7, "output_tokens": 3}



def test_first_runtime_rejects_remote_provider_route_at_publish_time(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    cp.configure_model_route(identity, "remote-route", "openrouter", "openai/gpt-4o-mini",
                              ["public"], ["remote"])
    remote_manifest = manifest()
    remote_manifest["model_routes"] = ["remote-route"]
    with pytest.raises(PermissionError, match="local Ollama"):
        cp.register_agent(identity, "remote-research", "1.0.0", remote_manifest)



def test_remote_runtime_requires_remote_route_and_explicit_residency(tmp_path):
    _, _, identity, cp = setup(tmp_path)
    cp.configure_model_route(identity, "remote-route", "openrouter", "openai/gpt-4o-mini",
                              ["public", "internal", "private"], ["unspecified"])
    remote_manifest = manifest([])
    remote_manifest["model_routes"] = ["remote-route"]
    remote_manifest["runtime"] = "oracle-arc-remote-agent-v1"
    registered = cp.register_agent(identity, "remote-research", "1.0.0", remote_manifest)
    assert registered.manifest["runtime"] == "oracle-arc-remote-agent-v1"

    invalid = dict(remote_manifest)
    invalid["model_routes"] = ["local-default"]
    configure(cp, identity)
    with pytest.raises(PermissionError, match="remote provider route"):
        cp.register_agent(identity, "remote-research-invalid", "1.0.0", invalid)


def test_remote_runtime_fails_closed_without_operator_opt_in(monkeypatch):
    from core.platform_runtime import RuntimeUnavailable, default_runtime_registry

    monkeypatch.delenv("ORACLE_ARC_ENABLE_REMOTE_INFERENCE", raising=False)
    with pytest.raises(RuntimeUnavailable, match="disabled by the platform operator"):
        default_runtime_registry().execute(
            "oracle-arc-remote-agent-v1",
            {"model_provider": "openrouter", "region": "unspecified",
             "classification": "public", "input_json": '{"messages":[{"role":"user","content":"hello"}]}'},
            {"runtime": "oracle-arc-remote-agent-v1", "allowed_tools": []})
