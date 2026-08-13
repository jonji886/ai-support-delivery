from datetime import datetime, timedelta, timezone
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


def test_slots_record_source_confidence_scope_and_expiry(tmp_path: Path) -> None:
    now = datetime(2026, 8, 13, tzinfo=timezone.utc)
    store = ConversationStore(db_path=str(tmp_path / "conversation.db"), clock=lambda: now)

    store.save(
        "session-1", user_id="user-1", order_id="OD202608001", intent="return", resolved=False,
        return_reason="尺码不合适", slot_sources={"order_id": "user_explicit", "return_reason": "user_explicit"},
    )

    context = store.get("session-1", "user-1")
    assert context["slots"]["order_id"]["source"] == "user_explicit"
    assert context["slots"]["order_id"]["confidence"] == 1.0
    assert context["slots"]["return_reason"]["scope_order_id"] == "OD202608001"
    assert context["slots"]["return_reason"]["expires_at"]


def test_switching_order_invalidates_order_scoped_slots(tmp_path: Path) -> None:
    store = ConversationStore(db_path=str(tmp_path / "conversation.db"))
    store.save(
        "session-1", user_id="user-1", order_id="OD202608001", intent="return", resolved=False,
        return_reason="尺码不合适", slot_sources={"order_id": "user_explicit", "return_reason": "user_explicit"},
    )

    store.save(
        "session-1", user_id="user-1", order_id="OD202608009", intent="logistics", resolved=True,
        slot_sources={"order_id": "user_correction"},
    )

    context = store.get("session-1", "user-1")
    assert context["order_id"] == "OD202608009"
    assert context.get("return_reason") is None
    assert "return_reason" not in context["slots"]


def test_expired_slot_is_not_returned_as_memory(tmp_path: Path) -> None:
    current = [datetime(2026, 8, 13, tzinfo=timezone.utc)]
    store = ConversationStore(db_path=str(tmp_path / "conversation.db"), clock=lambda: current[0], slot_ttl_minutes={"return_reason": 5})
    store.save(
        "session-1", user_id="user-1", order_id="OD202608001", intent="return", resolved=False,
        return_reason="尺码不合适", slot_sources={"order_id": "user_explicit", "return_reason": "user_explicit"},
    )

    current[0] += timedelta(minutes=6)
    context = store.get("session-1", "user-1")

    assert context is not None
    assert context.get("return_reason") is None
    assert "return_reason" not in context["slots"]


def test_expired_intent_is_not_returned_from_legacy_column(tmp_path: Path) -> None:
    current = [datetime(2026, 8, 13, tzinfo=timezone.utc)]
    store = ConversationStore(db_path=str(tmp_path / "conversation.db"), clock=lambda: current[0], slot_ttl_minutes={"last_intent": 5})
    store.save("session-1", user_id="user-1", order_id="OD202608001", intent="return", resolved=True)

    current[0] += timedelta(minutes=6)

    assert store.get("session-1", "user-1")["last_intent"] is None


def test_verified_fact_has_short_ttl_and_tool_source(tmp_path: Path) -> None:
    store = ConversationStore(db_path=str(tmp_path / "conversation.db"))

    store.save(
        "session-1", user_id="user-1", order_id="OD202608001", intent="logistics", resolved=True,
        verified_facts={"logistics": {"order_status": "运输中"}}, slot_sources={"order_id": "user_explicit"},
    )

    slot = store.get("session-1", "user-1")["slots"]["verified_logistics"]
    assert slot["source"] == "tool_verified"
    assert slot["scope_order_id"] == "OD202608001"
    assert slot["expires_at"]


def test_new_order_can_store_new_explicit_return_reason(tmp_path: Path) -> None:
    store = ConversationStore(db_path=str(tmp_path / "conversation.db"))
    store.save(
        "session-1", user_id="user-1", order_id="OD202608001", intent="return", resolved=False,
        return_reason="尺码不合适", slot_sources={"order_id": "user_explicit", "return_reason": "user_explicit"},
    )

    store.save(
        "session-1", user_id="user-1", order_id="OD202608009", intent="return", resolved=True,
        return_reason="不喜欢", slot_sources={"order_id": "user_correction", "return_reason": "user_explicit"},
    )

    context = store.get("session-1", "user-1")
    assert context["return_reason"] == "不喜欢"
    assert context["slots"]["return_reason"]["scope_order_id"] == "OD202608009"


def test_slot_ttls_can_be_configured_from_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CONVERSATION_TTL_HOURS", "8")
    monkeypatch.setenv("LOGISTICS_FACT_TTL_MINUTES", "2")
    store = ConversationStore(db_path=str(tmp_path / "conversation.db"))

    assert store.ttl == timedelta(hours=8)
    assert store.slot_ttl_minutes["verified_logistics"] == 2


def test_non_positive_ttl_configuration_fails_fast(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("INTENT_SLOT_TTL_MINUTES", "0")

    try:
        ConversationStore(db_path=str(tmp_path / "conversation.db"))
    except ValueError as error:
        assert "TTL values must be positive" in str(error)
    else:
        raise AssertionError("non-positive TTL must fail fast")
