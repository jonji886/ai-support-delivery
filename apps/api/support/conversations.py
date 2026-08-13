"""SQLite-backed, tenant/user-scoped conversation context for the MVP."""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


class ConversationStore:
    def __init__(self, db_path: Optional[str] = None, ttl_hours: int = 24) -> None:
        self.db_path = db_path or os.getenv("CONVERSATION_DB_PATH", "runtime/conversations.db")
        self.ttl = timedelta(hours=ttl_hours)
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
                    updated_at TEXT NOT NULL
                )"""
            )

    def get(self, session_id: Optional[str], user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        if not session_id:
            return None
        cutoff = (datetime.now(timezone.utc) - self.ttl).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_context WHERE session_id = ? AND updated_at >= ?",
                (session_id, cutoff),
            ).fetchone()
        if row is None or (user_id and row["user_id"] and row["user_id"] != user_id):
            return None
        return dict(row)

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
    ) -> None:
        if not session_id:
            return
        previous = self.get(session_id) or {}
        count = unresolved_count if unresolved_count is not None else (
            0 if resolved else int(previous.get("unresolved_count", 0)) + 1
        )
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO conversation_context
                   (session_id, user_id, order_id, last_intent, unresolved_count, return_reason, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                   user_id=COALESCE(excluded.user_id, conversation_context.user_id),
                   order_id=COALESCE(excluded.order_id, conversation_context.order_id),
                   last_intent=excluded.last_intent,
                   unresolved_count=excluded.unresolved_count,
                   return_reason=COALESCE(excluded.return_reason, conversation_context.return_reason),
                   updated_at=excluded.updated_at""",
                (session_id, user_id or previous.get("user_id"), order_id or previous.get("order_id"), intent, count, return_reason or previous.get("return_reason"), datetime.now(timezone.utc).isoformat()),
            )

    def clear(self, session_id: Optional[str]) -> None:
        if session_id:
            with self._connect() as connection:
                connection.execute("DELETE FROM conversation_context WHERE session_id = ?", (session_id,))

    def purge_expired(self) -> int:
        cutoff = (datetime.now(timezone.utc) - self.ttl).isoformat()
        with self._connect() as connection:
            result = connection.execute("DELETE FROM conversation_context WHERE updated_at < ?", (cutoff,))
            return result.rowcount
