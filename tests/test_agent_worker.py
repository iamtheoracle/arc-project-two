from core.agent_registry import AgentDefinition, AgentRegistry, Connector
from core.agent_worker import process_one
from core.store import ArcStore


def test_independent_worker_claims_executes_and_persists_task_result(tmp_path, monkeypatch):
    store = ArcStore(tmp_path / "worker.sqlite3")
    payload = {
        "model": "qwen2.5:7b", "history": [],
        "latest_user": "Explain simply", "max_steps": 2,
    }
    task = store.create_agent_task("worker-task-1", "bud", "oracle", ["reasoning"], payload)
    assert task["payload"] == payload

    registry = AgentRegistry()
    registry.register_agent(AgentDefinition("oracle", "ORACLE", "Reasoning", ("reasoning",)))
    registry.register_connector("oracle", Connector(
        "test-local", "test", 1, lambda data: "A simple answer"
    ))
    monkeypatch.setattr("api._build_agent_registry", lambda _store: registry)

    assert process_one(store, "worker-test-1") is True
    saved = store.get_agent_task("worker-task-1")
    assert saved["status"] == "succeeded"
    assert saved["worker_id"] is None
    assert saved["result"] == {"answer": "A simple answer"}
    assert saved["connector_id"] == "test-local"


def test_independent_worker_leaves_queue_empty_without_claiming(tmp_path):
    store = ArcStore(tmp_path / "empty-worker.sqlite3")
    assert process_one(store, "worker-test-2") is False
