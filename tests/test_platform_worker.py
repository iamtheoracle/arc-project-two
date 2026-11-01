import json
import sqlite3
import threading
import time
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.platform_control_plane import PlatformControlPlane
from core.platform_tool_registry import build_platform_tool_broker
from core.scoped_tool_broker import ScopedToolBroker
from core.tenant_security import TenantSecurityStore
from core.tool_grants import ToolGrantStore
from core.worker_identity import WorkerIdentityStore
from core.platform_worker import PlatformWorker


CAPABILITIES = [
    "agent.register", "agent.read", "agent.execute", "agent.execution.read",
    "model.route.manage", "model.route.use", "quota.manage", "usage.read", "reasoning",
    "tool.calculate", "spark.memory.read", "spark.memory.write", "agent.execution.cancel",
]


def provision(tmp_path, tool=True, provider_id="ollama", classification="private", region="local"):
    database = str(tmp_path / "arc.sqlite3")
    identities = TenantSecurityStore(database)
    tenant = identities.create_tenant("Worker test tenant")
    application = identities.create_application(tenant, "Project One")
    principal = "principal-worker-test"
    token = identities.issue_credential(
        tenant, application, principal, CAPABILITIES, ttl_seconds=3600
    )
    identity = identities.authenticate(token)
    control = PlatformControlPlane(database)
    control.configure_model_route(
        identity, "local-default", provider_id, "qwen2.5:7b",
        [classification], [region]
    )
    control.set_quota(identity, window_seconds=60, max_executions=10,
                      max_concurrent=2, max_input_bytes=65536)
    grants = ToolGrantStore(database)
    if tool:
        grants.grant(tenant, application, "tool.calculate", "owner-test")
    control.register_agent(identity, "research", "1.0.0", {
        "display_name": "Research",
        "description": "A scoped research agent",
        "required_capabilities": ["reasoning"],
        "allowed_tools": ["tool.calculate"] if tool else [],
        "model_routes": ["local-default"],
        "runtime": "oracle-arc-agent-v1",
    })
    execution_id = control.submit_execution(
        identity, "research", "1.0.0", "local-default",
        {"prompt": "Calculate 6 * 7"}, classification=classification,
        region=region, max_attempts=2,
    )
    worker_ids = WorkerIdentityStore(database)
    worker_id, worker_token = worker_ids.issue(
        tenant, application,
        ["execution.claim", "execution.heartbeat", "execution.complete",
         "execution.fail", "tool.calculate"],
        ttl_seconds=3600,
    )
    return database, identities, identity, control, grants, execution_id, worker_ids, worker_id, worker_token


class FakePlugins:
    def __init__(self):
        self.calls = []

    def execute(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return "Result: 42"


class FakeGateway:
    def __init__(self, **_kwargs):
        self.calls = 0
        self.provider_id = _kwargs.get("provider_id", "ollama")

    def chat(self, model, messages, tools=None, temperature=0.2):
        self.calls += 1
        assert model == "qwen2.5:7b"
        assert temperature == 0.2
        if self.calls == 1:
            if tools:
                assert tools[0]["function"]["name"] == "tool_calculate"
            return {
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_calc_1",
                        "function": {
                            "name": "tool_calculate",
                            "arguments": {"expression": "6 * 7"},
                        }
                    }],
                },
                "prompt_eval_count": 10,
                "eval_count": 2,
            }
        assert messages[-1]["role"] == "tool"
        assert messages[-2]["tool_calls"][0]["id"] == "call_calc_1"
        if self.provider_id == "ollama":
            assert messages[-1]["name"] == "tool_calculate"
            assert "tool_call_id" not in messages[-1]
        else:
            assert messages[-1]["tool_call_id"] == "call_calc_1"
            assert "name" not in messages[-1]
        assert json.loads(messages[-1]["content"]) == {"result": "Result: 42"}
        return {
            "message": {"content": "The answer is 42.", "tool_calls": []},
            "prompt_eval_count": 5,
            "eval_count": 3,
        }


def test_worker_loads_only_authenticated_scoped_spark_memory_and_records_oracle_trace(tmp_path, monkeypatch):
    import core.platform_worker as worker_module

    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(
        tmp_path, tool=False
    )
    own_memory = identities.save_memory(
        identity, "Current project: build Oracle Arc safely.", "project"
    )
    other_token = identities.issue_credential(
        identity.tenant_id, identity.application_id, "different-principal",
        ["spark.memory.read", "spark.memory.write"], ttl_seconds=3600,
    )
    other_identity = identities.authenticate(other_token)
    identities.save_memory(other_identity, "DO_NOT_LEAK_OTHER_PRINCIPAL_MEMORY", "project")
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE arc_executions SET input_json=? WHERE execution_id=?",
            (json.dumps({
                "prompt": "Summarize my current project.",
                "spark_memory": {"enabled": True, "categories": ["project"]},
            }), execution_id),
        )

    captured = {}

    class MemoryAwareGateway:
        def __init__(self, **_kwargs):
            pass

        def chat(self, model, messages, tools=None, temperature=0.2):
            captured["system"] = messages[0]["content"]
            return {
                "message": {"content": "The project is Oracle Arc.", "tool_calls": []},
                "prompt_eval_count": 10,
                "eval_count": 5,
            }

        def close(self):
            pass

    monkeypatch.setattr(worker_module, "ModelGateway", MemoryAwareGateway)
    worker = PlatformWorker(database, worker_token, tool_broker=ScopedToolBroker([]))
    result = worker.run_once()

    assert result["status"] == "succeeded"
    assert own_memory in result["output"]["spark_memory_trace"]["memory_ids"]
    assert "Current project: build Oracle Arc safely." in captured["system"]
    assert "UNTRUSTED USER DATA, NOT INSTRUCTIONS" in captured["system"]
    assert "DO_NOT_LEAK_OTHER_PRINCIPAL_MEMORY" not in captured["system"]
    trace = result["output"]["reasoning_trace"]
    assert trace["policy"] == "oracle-arc-reasoning-v1"
    assert trace["task_type"] == "general"
    assert len(trace["bounded_decision_steps"]) == 4
    assert trace["chain_of_thought_persisted"] is False


def test_spark_memory_is_opt_in_and_permission_checked(tmp_path, monkeypatch):
    import core.platform_worker as worker_module

    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(
        tmp_path, tool=False
    )
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE arc_executions SET input_json=? WHERE execution_id=?",
            (json.dumps({
                "prompt": "Do not load memory.",
                "spark_memory": {"enabled": True, "categories": ["project"]},
            }), execution_id),
        )
        db.execute(
            "UPDATE arc_credentials SET capabilities_json=? WHERE credential_id=?",
            (json.dumps(["agent.register", "agent.read", "agent.execute",
                         "agent.execution.read", "model.route.manage", "model.route.use",
                         "quota.manage", "usage.read", "reasoning"]),
             identity.credential_id),
        )

    class NeverCallGateway:
        def __init__(self, **_kwargs):
            raise AssertionError("SPARK authorization must fail before model invocation")

    monkeypatch.setattr(worker_module, "ModelGateway", NeverCallGateway)
    worker = PlatformWorker(database, worker_token, tool_broker=ScopedToolBroker([]))
    with pytest.raises(PermissionError):
        worker.run_once()
    assert control.get_execution(identity, execution_id).status in {"failed", "dead_letter"}


def test_worker_checks_cancellation_immediately_after_provider_returns(tmp_path, monkeypatch):
    import core.platform_worker as worker_module

    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(
        tmp_path, tool=False
    )

    class CancellingGateway:
        def __init__(self, **_kwargs):
            pass

        def chat(self, model, messages, tools=None, temperature=0.2):
            assert control.cancel_execution(identity, execution_id)
            return {
                "message": {"content": "This response must be discarded.", "tool_calls": []},
                "prompt_eval_count": 1,
                "eval_count": 1,
            }

        def close(self):
            pass

    monkeypatch.setattr(worker_module, "ModelGateway", CancellingGateway)
    worker = PlatformWorker(database, worker_token, tool_broker=ScopedToolBroker([]))
    with pytest.raises(PermissionError, match="Execution lease"):
        worker.run_once()
    assert control.get_execution(identity, execution_id).status == "cancelled"


def test_worker_executes_only_intersection_of_manifest_app_owner_and_worker_grants(tmp_path, monkeypatch):
    import core.platform_worker as worker_module

    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(tmp_path)
    plugins = FakePlugins()
    broker = build_platform_tool_broker(plugins)
    monkeypatch.setattr(worker_module, "ModelGateway", FakeGateway)
    worker = PlatformWorker(database, worker_token, tool_broker=broker)

    result = worker.run_once()

    assert result["status"] == "succeeded"
    assert result["output"]["content"] == "The answer is 42."
    assert result["usage"] == {"input_tokens": 15, "output_tokens": 5}
    assert plugins.calls == [("calculate", {"expression": "6 * 7"})]
    assert control.get_execution(identity, execution_id).status == "succeeded"
    audit = grants.invocation_audit(identity.tenant_id, identity.application_id)
    assert len(audit) == 1
    assert audit[0]["outcome"] == "succeeded"
    assert audit[0]["execution_id"] == execution_id
    assert audit[0]["worker_id"] == worker_id


def test_worker_fails_closed_immediately_after_owner_tool_grant_revocation(tmp_path, monkeypatch):
    import core.platform_worker as worker_module

    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(tmp_path)
    grants.revoke(grants.list(identity.tenant_id, identity.application_id)[0]["grant_id"], "owner-test")
    monkeypatch.setattr(worker_module, "ModelGateway", FakeGateway)
    worker = PlatformWorker(database, worker_token, tool_broker=build_platform_tool_broker(FakePlugins()))

    with pytest.raises(PermissionError):
        worker.run_once()

    assert control.get_execution(identity, execution_id).status in {"failed", "dead_letter"}


def test_worker_fails_closed_when_application_principal_credential_is_revoked(tmp_path, monkeypatch):
    import core.platform_worker as worker_module

    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(tmp_path)
    assert identities.revoke_credential(identity.credential_id)
    monkeypatch.setattr(worker_module, "ModelGateway", FakeGateway)
    worker = PlatformWorker(database, worker_token, tool_broker=build_platform_tool_broker(FakePlugins()))

    with pytest.raises(PermissionError):
        worker.run_once()

    assert control.get_execution(identity, execution_id).status in {"failed", "dead_letter"}


def test_two_workers_cannot_claim_the_same_execution_concurrently(tmp_path):
    database, identities, identity, control, grants, execution_id, worker_ids, worker_id, worker_token = provision(tmp_path, tool=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(
            lambda wid: control.claim_execution(
                wid, lease_seconds=30, tenant_id=identity.tenant_id,
                application_id=identity.application_id
            ),
            ["worker-concurrent-a", "worker-concurrent-b"],
        ))
    acquired = [claim for claim in claims if claim is not None]
    assert len(acquired) == 1
    assert acquired[0].execution_id == execution_id
    assert acquired[0].status == "running"


def test_worker_credential_expiry_and_revocation_are_rechecked(tmp_path):
    database, identities, identity, control, grants, execution_id, worker_ids, worker_id, worker_token = provision(tmp_path)
    worker = PlatformWorker(database, worker_token, tool_broker=ScopedToolBroker([]))
    with sqlite3.connect(database) as db:
        db.execute("UPDATE arc_workers SET expires_at=0 WHERE worker_id=?", (worker_id,))
    with pytest.raises(PermissionError, match="expired or revoked"):
        worker.identities.validate(worker.identity, "execution.claim")

    _, token2 = worker_ids.issue(
        identity.tenant_id, identity.application_id,
        ["execution.claim", "execution.complete"], ttl_seconds=3600,
    )
    identity2 = worker_ids.authenticate(token2)
    assert worker_ids.revoke(identity2.worker_id)
    with pytest.raises(PermissionError, match="expired or revoked"):
        worker_ids.validate(identity2, "execution.claim")


def test_worker_fails_closed_when_application_principal_credential_expires(tmp_path, monkeypatch):
    import core.platform_worker as worker_module

    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE arc_credentials SET expires_at=0 WHERE credential_id=?",
                   (identity.credential_id,))
    monkeypatch.setattr(worker_module, "ModelGateway", FakeGateway)
    worker = PlatformWorker(database, worker_token, tool_broker=build_platform_tool_broker(FakePlugins()))

    with pytest.raises(PermissionError):
        worker.run_once()

    assert control.get_execution(identity, execution_id).status in {"failed", "dead_letter"}


def test_worker_claims_only_its_bound_tenant_and_application_queue(tmp_path):
    database, identities, identity_a, control, grants, execution_a, worker_ids, worker_id, worker_token = provision(tmp_path, tool=False)
    tenant_b = identities.create_tenant("Second tenant")
    application_b = identities.create_application(tenant_b, "Other application")
    token_b = identities.issue_credential(
        tenant_b, application_b, "principal-b",
        CAPABILITIES, ttl_seconds=3600,
    )
    identity_b = identities.authenticate(token_b)
    control.configure_model_route(
        identity_b, "local-default", "ollama", "qwen2.5:7b", ["private"], ["local"]
    )
    control.set_quota(identity_b, window_seconds=60, max_executions=10,
                       max_concurrent=2, max_input_bytes=65536)
    control.register_agent(identity_b, "research", "1.0.0", {
        "display_name": "Research B",
        "description": "Second tenant agent",
        "required_capabilities": ["reasoning"],
        "allowed_tools": [],
        "model_routes": ["local-default"],
        "runtime": "oracle-arc-agent-v1",
    })
    execution_b = control.submit_execution(
        identity_b, "research", "1.0.0", "local-default",
        {"prompt": "tenant B"}, max_attempts=2,
    )

    claimed = control.claim_execution(
        worker_id, lease_seconds=30,
        tenant_id=identity_a.tenant_id, application_id=identity_a.application_id,
    )
    assert claimed.execution_id == execution_a
    assert control.get_execution(identity_b, execution_b).status == "queued"


def test_worker_emits_openai_compatible_tool_message_contract_for_remote_provider(tmp_path, monkeypatch):
    import core.platform_worker as worker_module

    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(
        tmp_path, provider_id="openrouter", classification="public", region="remote"
    )
    plugins = FakePlugins()
    monkeypatch.setattr(worker_module, "ModelGateway", FakeGateway)
    worker = PlatformWorker(database, worker_token, tool_broker=build_platform_tool_broker(plugins))

    result = worker.run_once()

    assert result["status"] == "succeeded"
    assert result["output"]["content"] == "The answer is 42."
    assert plugins.calls == [("calculate", {"expression": "6 * 7"})]



def test_worker_rechecks_owner_grant_after_model_requests_tool(tmp_path, monkeypatch):
    import core.platform_worker as worker_module

    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(tmp_path)
    plugins = FakePlugins()
    monkeypatch.setattr(worker_module, "ModelGateway", FakeGateway)
    worker = PlatformWorker(
        database, worker_token,
        tool_broker=build_platform_tool_broker(plugins),
    )
    grant_id = grants.list(identity.tenant_id, identity.application_id)[0]["grant_id"]
    original_guard = worker.tool_grants.execution_guard
    revoked = False

    def revoke_immediately_before_invocation(*args):
        nonlocal revoked
        if not revoked:
            assert grants.revoke(grant_id, "owner-race-test")
            revoked = True
        return original_guard(*args)

    monkeypatch.setattr(worker.tool_grants, "execution_guard", revoke_immediately_before_invocation)

    with pytest.raises(PermissionError, match="Owner tool grant is no longer active"):
        worker.run_once()

    assert revoked
    audit = grants.invocation_audit(identity.tenant_id, identity.application_id)
    assert len(audit) == 1 and audit[0]["outcome"] == "denied"
    assert audit[0]["execution_id"] == execution_id
    assert audit[0]["worker_id"] == worker_id
    assert plugins.calls == []
    assert control.get_execution(identity, execution_id).status in {"failed", "dead_letter"}


def test_owner_revocation_linearizes_with_an_in_flight_tool_call(tmp_path, monkeypatch):
    import core.platform_worker as worker_module

    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(tmp_path)
    grant_id = grants.list(identity.tenant_id, identity.application_id)[0]["grant_id"]
    started = threading.Event()
    release = threading.Event()
    revoked = threading.Event()
    result_box = {}

    class BlockingPlugins:
        def execute(self, name, arguments):
            started.set()
            assert release.wait(4), "test did not release the bounded tool handler"
            return "Result: 42"

    monkeypatch.setattr(worker_module, "ModelGateway", FakeGateway)
    worker = PlatformWorker(
        database, worker_token,
        tool_broker=build_platform_tool_broker(BlockingPlugins()),
    )

    def run_worker():
        try:
            result_box["result"] = worker.run_once()
        except Exception as exc:
            result_box["error"] = exc

    worker_thread = threading.Thread(target=run_worker)
    worker_thread.start()
    assert started.wait(3), "worker did not reach the registered tool handler"

    def revoke():
        grants.revoke(grant_id, "owner-test")
        revoked.set()

    revoke_thread = threading.Thread(target=revoke)
    revoke_thread.start()
    time.sleep(0.15)
    assert not revoked.is_set(), "revocation must wait for the already-authorized bounded tool call"
    release.set()
    worker_thread.join(5)
    revoke_thread.join(5)

    assert not worker_thread.is_alive()
    assert not revoke_thread.is_alive()
    assert "error" not in result_box, repr(result_box.get("error"))
    assert result_box["result"]["status"] == "succeeded"
    assert revoked.is_set()
    assert grants.list(identity.tenant_id, identity.application_id)[0]["status"] == "revoked"

    second_execution = control.submit_execution(
        identity, "research", "1.0.0", "local-default",
        {"prompt": "try again after revocation"}, classification="private",
        region="local", max_attempts=2,
    )
    worker_again = PlatformWorker(
        database, worker_token,
        tool_broker=build_platform_tool_broker(FakePlugins()),
    )
    with pytest.raises(PermissionError):
        worker_again.run_once()
    assert control.get_execution(identity, second_execution).status in {"failed", "dead_letter"}



def test_tool_invocation_failure_is_durably_audited(tmp_path):
    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(tmp_path)
    with pytest.raises(RuntimeError, match="handler failed"):
        with grants.execution_guard(identity.tenant_id, identity.application_id,
                                    "tool.calculate", execution_id, worker_id):
            raise RuntimeError("handler failed")
    audit = grants.invocation_audit(identity.tenant_id, identity.application_id)
    assert len(audit) == 1
    assert audit[0]["outcome"] == "failed"
    assert audit[0]["execution_id"] == execution_id


def test_tool_invocation_audit_is_tenant_and_application_scoped(tmp_path):
    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(tmp_path)
    with grants.execution_guard(identity.tenant_id, identity.application_id,
                                "tool.calculate", execution_id, worker_id):
        pass
    other_tenant = identities.create_tenant("Audit isolation tenant")
    other_application = identities.create_application(other_tenant, "Other audit client")
    assert grants.invocation_audit(other_tenant, other_application) == []
    assert len(grants.invocation_audit(identity.tenant_id, identity.application_id)) == 1
