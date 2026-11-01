import json
import sqlite3
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
    "tool.calculate",
]


def provision(tmp_path, tool=True):
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
        identity, "local-default", "ollama", "qwen2.5:7b", ["private"], ["local"]
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
        {"prompt": "Calculate 6 * 7"}, max_attempts=2,
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

    def chat(self, model, messages, tools=None, temperature=0.2):
        self.calls += 1
        assert model == "qwen2.5:7b"
        assert temperature == 0.2
        assert tools and tools[0]["function"]["name"] == "tool.calculate"
        if self.calls == 1:
            return {
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_calc_1",
                        "function": {
                            "name": "tool.calculate",
                            "arguments": {"expression": "6 * 7"},
                        }
                    }],
                },
                "prompt_eval_count": 10,
                "eval_count": 2,
            }
        assert messages[-1]["role"] == "tool"
        assert messages[-1]["tool_call_id"] == "call_calc_1"
        assert json.loads(messages[-1]["content"]) == {"result": "Result: 42"}
        return {
            "message": {"content": "The answer is 42.", "tool_calls": []},
            "prompt_eval_count": 5,
            "eval_count": 3,
        }


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


def test_worker_fails_closed_immediately_after_owner_tool_grant_revocation(tmp_path, monkeypatch):
    import core.platform_worker as worker_module

    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(tmp_path)
    grants.revoke(grants.list(identity.tenant_id, identity.application_id)[0]["grant_id"], "owner-test")
    monkeypatch.setattr(worker_module, "ModelGateway", FakeGateway)
    worker = PlatformWorker(database, worker_token, tool_broker=build_platform_tool_broker(FakePlugins()))

    with pytest.raises(PermissionError, match="No declared agent tools"):
        worker.run_once()

    assert control.get_execution(identity, execution_id).status in {"failed", "dead_letter"}


def test_worker_fails_closed_when_application_principal_credential_is_revoked(tmp_path, monkeypatch):
    import core.platform_worker as worker_module

    database, identities, identity, control, grants, execution_id, _, worker_id, worker_token = provision(tmp_path)
    assert identities.revoke_credential(identity.credential_id)
    monkeypatch.setattr(worker_module, "ModelGateway", FakeGateway)
    worker = PlatformWorker(database, worker_token, tool_broker=build_platform_tool_broker(FakePlugins()))

    with pytest.raises(PermissionError, match="No declared agent tools"):
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

    with pytest.raises(PermissionError, match="No declared agent tools"):
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
