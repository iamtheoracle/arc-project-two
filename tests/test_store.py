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
