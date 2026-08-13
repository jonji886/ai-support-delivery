from pathlib import Path

from apps.api.support.conversations import ConversationStore


def test_conversation_context_survives_new_store_instance(tmp_path: Path) -> None:
    db = str(tmp_path / "conversation.db")
    first = ConversationStore(db_path=db)
    first.save("session-1", user_id="user-1", order_id="OD202608001", intent="logistics", resolved=True)
    second = ConversationStore(db_path=db)
    assert second.get("session-1", "user-1")["order_id"] == "OD202608001"


def test_conversation_context_rejects_other_user(tmp_path: Path) -> None:
    store = ConversationStore(db_path=str(tmp_path / "conversation.db"))
    store.save("session-1", user_id="user-1", order_id="OD202608001", intent="logistics", resolved=True)
    assert store.session_belongs_to_other_user("session-1", "user-2") is True
    assert store.get("session-1", "user-2") is None
