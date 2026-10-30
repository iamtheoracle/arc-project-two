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
