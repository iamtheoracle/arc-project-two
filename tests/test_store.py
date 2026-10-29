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
    assert reopened.delete_memory(memory["id"]) is True
    assert reopened.delete_memory(memory["id"]) is False
