"""SQLite-backed, user-scoped short-term business state.

Conversation text is not treated as memory. Only explicit slots and verified
facts with provenance, confidence, scope and expiry can be inherited.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional


DEFAULT_SLOT_TTL_MINUTES = {
    "order_id": 24 * 60,
    "return_reason": 60,
    "last_intent": 30,
    "verified_logistics": 5,
    "verified_return": 15,
}

SLOT_TTL_ENV_VARS = {
    "order_id": "ORDER_SLOT_TTL_MINUTES",
    "return_reason": "RETURN_REASON_SLOT_TTL_MINUTES",
    "last_intent": "INTENT_SLOT_TTL_MINUTES",
    "verified_logistics": "LOGISTICS_FACT_TTL_MINUTES",
    "verified_return": "RETURN_FACT_TTL_MINUTES",
}


class ConversationStore:
    def __init__(
        self,
        db_path: Optional[str] = None,
        ttl_hours: Optional[int] = None,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        slot_ttl_minutes: Optional[dict[str, int]] = None,
    ) -> None:
        self.db_path = db_path or os.getenv("CONVERSATION_DB_PATH", "runtime/conversations.db")
        configured_ttl_hours = ttl_hours if ttl_hours is not None else int(os.getenv("CONVERSATION_TTL_HOURS", "24"))
        self.ttl = timedelta(hours=configured_ttl_hours)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.slot_ttl_minutes = {
            name: int(os.getenv(SLOT_TTL_ENV_VARS[name], str(default_minutes)))
            for name, default_minutes in DEFAULT_SLOT_TTL_MINUTES.items()
        }
        self.slot_ttl_minutes.update(slot_ttl_minutes or {})
        if configured_ttl_hours <= 0 or any(value <= 0 for value in self.slot_ttl_minutes.values()):
            raise ValueError("conversation and slot TTL values must be positive")
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS conversation_context (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    order_id TEXT,
                    last_intent TEXT NOT NULL,
                    unresolved_count INTEGER NOT NULL DEFAULT 0,
                    return_reason TEXT,
                    updated_at TEXT NOT NULL,
                    slots_json TEXT NOT NULL DEFAULT '{}'
                )"""
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(conversation_context)")}
            if "slots_json" not in columns:
                connection.execute("ALTER TABLE conversation_context ADD COLUMN slots_json TEXT NOT NULL DEFAULT '{}'")

    def _now(self) -> datetime:
        current = self.clock()
        return current if current.tzinfo else current.replace(tzinfo=timezone.utc)

    def _slot(
        self,
        name: str,
        value: Any,
        *,
        source: str,
        confidence: float,
        scope_order_id: Optional[str] = None,
    ) -> dict[str, Any]:
        now = self._now()
        ttl = timedelta(minutes=self.slot_ttl_minutes[name])
        return {
            "name": name,
            "value": value,
            "source": source,
            "confidence": confidence,
            "scope": "order" if scope_order_id else "session",
            "scope_order_id": scope_order_id,
            "recorded_at": now.isoformat(),
            "expires_at": (now + ttl).isoformat(),
        }

    def get(self, session_id: Optional[str], user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        if not session_id:
            return None
        cutoff = (self._now() - self.ttl).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_context WHERE session_id = ? AND updated_at >= ?",
                (session_id, cutoff),
            ).fetchone()
        if row is None or (user_id and row["user_id"] and row["user_id"] != user_id):
            return None
        result = dict(row)
        raw_slots = json.loads(result.pop("slots_json") or "{}")
        if not raw_slots:
            # Existing MVP databases predate slot provenance. Migrate their
            # explicit columns conservatively using the original updated time.
            recorded_at = datetime.fromisoformat(result["updated_at"])
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=timezone.utc)

            def legacy_slot(name: str, value: Any, scope_order_id: Optional[str] = None) -> dict[str, Any]:
                return {
                    "name": name,
                    "value": value,
                    "source": "legacy_migration",
                    "confidence": 0.80,
                    "scope": "order" if scope_order_id else "session",
                    "scope_order_id": scope_order_id,
                    "recorded_at": recorded_at.isoformat(),
                    "expires_at": (recorded_at + timedelta(minutes=self.slot_ttl_minutes[name])).isoformat(),
                }

            if result.get("order_id"):
                raw_slots["order_id"] = legacy_slot("order_id", result["order_id"])
            if result.get("last_intent"):
                raw_slots["last_intent"] = legacy_slot("last_intent", result["last_intent"])
            if result.get("return_reason") and result.get("order_id"):
                raw_slots["return_reason"] = legacy_slot("return_reason", result["return_reason"], result["order_id"])
        now = self._now().isoformat()
        slots = {name: slot for name, slot in raw_slots.items() if slot.get("expires_at", "") > now}
        result["slots"] = slots
        result["order_id"] = slots.get("order_id", {}).get("value")
        result["return_reason"] = slots.get("return_reason", {}).get("value")
        result["last_intent"] = slots.get("last_intent", {}).get("value")
        return result

    def session_belongs_to_other_user(self, session_id: Optional[str], user_id: Optional[str]) -> bool:
        if not session_id or not user_id:
            return False
        with self._connect() as connection:
            row = connection.execute("SELECT user_id FROM conversation_context WHERE session_id = ?", (session_id,)).fetchone()
        return bool(row and row["user_id"] and row["user_id"] != user_id)

    def save(
        self,
        session_id: Optional[str],
        *,
        user_id: Optional[str],
        order_id: Optional[str],
        intent: str,
        resolved: bool,
        unresolved_count: Optional[int] = None,
        return_reason: Optional[str] = None,
        slot_sources: Optional[dict[str, str]] = None,
        verified_facts: Optional[dict[str, Any]] = None,
    ) -> None:
        if not session_id:
            return
        previous = self.get(session_id) or {}
        previous_slots = dict(previous.get("slots") or {})
        sources = slot_sources or {}
        previous_order_id = previous_slots.get("order_id", {}).get("value")
        order_changed = bool(order_id and previous_order_id and order_id != previous_order_id)
        if order_changed:
            # Order-scoped slots and verified facts cannot cross an explicit
            # order correction. Session-level intent is replaced below.
            previous_slots = {
                name: slot for name, slot in previous_slots.items()
                if slot.get("scope") != "order"
            }
        effective_order_id = order_id or previous_order_id
        if order_id:
            previous_slots["order_id"] = self._slot(
                "order_id", order_id,
                source=sources.get("order_id", "user_explicit" if order_changed or not previous_order_id else "conversation_inherited"),
                confidence=1.0 if sources.get("order_id") in {"user_explicit", "user_correction"} or order_changed or not previous_order_id else 0.90,
            )
        previous_slots["last_intent"] = self._slot(
            "last_intent", intent, source=sources.get("last_intent", "intent_catalog"), confidence=0.99,
        )
        if return_reason:
            reason_source = sources.get("return_reason", "user_explicit")
            previous_reason = previous_slots.get("return_reason")
            if not (
                reason_source == "conversation_inherited"
                and previous_reason
                and previous_reason.get("value") == return_reason
                and not order_changed
            ):
                previous_slots["return_reason"] = self._slot(
                    "return_reason", return_reason,
                    source=reason_source, confidence=1.0 if reason_source != "conversation_inherited" else 0.90,
                    scope_order_id=effective_order_id,
                )
        for fact_name, value in (verified_facts or {}).items():
            slot_name = f"verified_{fact_name}"
            if slot_name not in self.slot_ttl_minutes:
                raise ValueError(f"unsupported verified fact slot: {slot_name}")
            previous_slots[slot_name] = self._slot(
                slot_name, value, source="tool_verified", confidence=1.0, scope_order_id=effective_order_id,
            )
        count = unresolved_count if unresolved_count is not None else (
            0 if resolved else int(previous.get("unresolved_count", 0)) + 1
        )
        now = self._now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO conversation_context
                   (session_id, user_id, order_id, last_intent, unresolved_count, return_reason, updated_at, slots_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                   user_id=COALESCE(excluded.user_id, conversation_context.user_id),
                   order_id=excluded.order_id,
                   last_intent=excluded.last_intent,
                   unresolved_count=excluded.unresolved_count,
                   return_reason=excluded.return_reason,
                   updated_at=excluded.updated_at,
                   slots_json=excluded.slots_json""",
                (
                    session_id, user_id or previous.get("user_id"), effective_order_id, intent, count,
                    previous_slots.get("return_reason", {}).get("value"), now,
                    json.dumps(previous_slots, ensure_ascii=False),
                ),
            )

    def clear(self, session_id: Optional[str]) -> None:
        if session_id:
            with self._connect() as connection:
                connection.execute("DELETE FROM conversation_context WHERE session_id = ?", (session_id,))

    def purge_expired(self) -> int:
        cutoff = (self._now() - self.ttl).isoformat()
        with self._connect() as connection:
            result = connection.execute("DELETE FROM conversation_context WHERE updated_at < ?", (cutoff,))
            return result.rowcount
