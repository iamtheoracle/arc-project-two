import pytest

from core.store import ArcStore


def test_memory_and_conversations_survive_store_reopen(tmp_path):
    path = tmp_path / "persistent.sqlite3"
    store = ArcStore(path)
    memory = store.save_memory("Oracle Arc belongs to me.", ["owner"])
    conversation_id = store.create_conversation("Persistent chat")
    store.add_message(conversation_id, "user", "Hello")
    store.set_tool_approval("calculate", True)

    reopened = ArcStore(path)
    assert reopened.list_memories()[0]["id"] == memory["id"]
    assert reopened.get_messages(conversation_id) == [{"role": "user", "content": "Hello"}]
    assert "calculate" in reopened.approved_tools()
    updated = reopened.update_memory(memory["id"], "Updated personal memory.", ["edited"])
    assert updated is not None
    assert updated["content"] == "Updated personal memory."
    assert reopened.delete_memory(memory["id"]) is True
    assert reopened.delete_memory(memory["id"]) is False
    assert reopened.delete_conversation(conversation_id) is True
    assert reopened.delete_conversation(conversation_id) is False



def test_failed_turn_rollback_removes_only_pending_message_and_empty_new_chat(tmp_path):
    store = ArcStore(tmp_path / "rollback.sqlite3")
    conversation_id = store.create_conversation("Keep earlier history")
    store.add_message(conversation_id, "user", "Earlier message")
    pending_id = store.add_message(conversation_id, "user", "Failed request")

    store.rollback_pending_turn(conversation_id, pending_id)
    assert store.get_messages(conversation_id) == [
        {"role": "user", "content": "Earlier message"}
    ]
    assert store.conversation_exists(conversation_id)

    empty_conversation = store.create_conversation("Failed first turn")
    empty_pending_id = store.add_message(empty_conversation, "user", "Failed first request")
    store.rollback_pending_turn(empty_conversation, empty_pending_id)
    assert not store.conversation_exists(empty_conversation)



def test_in_memory_store_is_shared_across_its_request_connections():
    store = ArcStore(":memory:")
    memory = store.save_memory("Visible across connections.")
    conversation_id = store.create_conversation("Memory-backed chat")
    store.add_message(conversation_id, "user", "Hello")

    assert store.list_memories()[0]["id"] == memory["id"]
    assert store.get_messages(conversation_id) == [
        {"role": "user", "content": "Hello"}
    ]

def test_message_event_ids_make_replicated_writes_idempotent(tmp_path):
    store = ArcStore(tmp_path / "idempotent.sqlite3")
    session_id = store.create_conversation("Replication")
    first = store.add_message(session_id, "user", "same event", event_id="event-123")
    second = store.add_message(session_id, "user", "same event", event_id="event-123")
    assert first > 0
    assert second == 0
    assert store.get_messages(session_id) == [{"role": "user", "content": "same event"}]

def test_agent_task_lifecycle_is_persisted_and_terminal_states_are_final(tmp_path):
    store = ArcStore(tmp_path / "agent-tasks.sqlite3")
    task = store.create_agent_task("task-abc", "bud", "oracle", ["reasoning"])
    assert task["status"] == "queued"
    assert task["required_capabilities"] == ["reasoning"]
    running = store.update_agent_task("task-abc", "running")
    assert running["status"] == "running"
    succeeded = store.update_agent_task(
        "task-abc", "succeeded", connector_id="ollama-oracle-primary", provider="ollama-local")
    assert succeeded["status"] == "succeeded"
    assert succeeded["connector_id"] == "ollama-oracle-primary"
    assert store.get_agent_task("task-abc") == succeeded
    with pytest.raises(ValueError, match="state transition"):
        store.update_agent_task("task-abc", "failed")


def test_agent_task_claim_is_atomic_and_bound_to_one_worker(tmp_path):
    store = ArcStore(tmp_path / "task-leases.sqlite3")
    store.create_agent_task("task-race", "bud", "oracle", ["reasoning"])
    first = store.claim_agent_task("worker-a", task_id="task-race", lease_seconds=30)
    second = store.claim_agent_task("worker-b", task_id="task-race", lease_seconds=30)
    assert first["worker_id"] == "worker-a"
    assert first["attempts"] == 1
    assert second is None
    assert store.renew_agent_task_lease("task-race", "worker-a", 45) is True
    assert store.renew_agent_task_lease("task-race", "worker-b", 45) is False
    with pytest.raises(ValueError, match="does not own"):
        store.update_agent_task("task-race", "succeeded", worker_id="worker-b")
    completed = store.update_agent_task("task-race", "succeeded", worker_id="worker-a")
    assert completed["status"] == "succeeded"
    assert completed["worker_id"] is None
    assert store.claim_agent_task("worker-c", task_id="task-race") is None


def test_expired_agent_task_lease_is_requeued_and_retry_limit_is_enforced(tmp_path):
    store = ArcStore(tmp_path / "task-recovery.sqlite3")
    store.create_agent_task("task-expired", "bud", "oracle", ["reasoning"])
    first = store.claim_agent_task("worker-crashed", task_id="task-expired", max_attempts=2)
    assert first["attempts"] == 1
    with store._session() as conn:
        conn.execute("UPDATE agent_tasks SET lease_expires_at=0 WHERE task_id='task-expired'")
    assert store.recover_expired_agent_tasks(max_attempts=2) == 1
    assert store.get_agent_task("task-expired")["status"] == "queued"
    second = store.claim_agent_task("worker-retry", task_id="task-expired", max_attempts=2)
    assert second["attempts"] == 2
    with store._session() as conn:
        conn.execute("UPDATE agent_tasks SET lease_expires_at=0 WHERE task_id='task-expired'")
    assert store.recover_expired_agent_tasks(max_attempts=2) == 1
    final = store.get_agent_task("task-expired")
    assert final["status"] == "failed"
    assert final["error_code"] == "worker_lease_expired"
    assert store.claim_agent_task("worker-third", task_id="task-expired", max_attempts=2) is None


def test_agent_task_outbox_is_transactional_leased_and_acknowledged(tmp_path):
    store = ArcStore(tmp_path / "task-outbox.sqlite3")
    store.create_agent_task("task-outbox", "bud", "oracle", ["reasoning"])
    events = store.claim_task_outbox("outbox-worker", limit=10)
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "task.queued"
    assert event["payload"]["task_id"] == "task-outbox"
    assert store.acknowledge_task_outbox(event["event_id"], "wrong-worker") is False
    assert store.acknowledge_task_outbox(event["event_id"], "outbox-worker") is True
    assert store.claim_task_outbox("another-worker") == []


def test_outbox_event_is_redelivered_after_worker_lease_expires(tmp_path):
    store = ArcStore(tmp_path / "outbox-recovery.sqlite3")
    store.create_agent_task("task-redeliver", "bud", "oracle", ["reasoning"])
    first = store.claim_task_outbox("worker-lost", lease_seconds=5)
    assert len(first) == 1
    with store._session() as conn:
        conn.execute(
            "UPDATE agent_task_outbox SET lease_expires_at=0 WHERE event_id=?",
            (first[0]["event_id"],),
        )
    second = store.claim_task_outbox("worker-replacement", lease_seconds=5)
    assert len(second) == 1
    assert second[0]["event_id"] == first[0]["event_id"]
    assert second[0]["attempts"] == 2
    assert store.acknowledge_task_outbox(first[0]["event_id"], "worker-lost") is False
    assert store.acknowledge_task_outbox(second[0]["event_id"], "worker-replacement") is True
