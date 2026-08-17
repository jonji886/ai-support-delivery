"""SQLite-backed persistent Memory Store。

统一存储 Conversation Memory 和 Long-term Memory。
Working Memory 仍由 ConversationStore 管理（保留现有实现）。

表结构：
  memories — 所有 Memory 记录，通过 memory_type 区分
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional


class MemoryRecord:
    """一条 Memory 记录。"""

    __slots__ = (
        "memory_id", "user_id", "memory_type", "key", "value",
        "source", "confidence", "scope", "scope_order_id",
        "session_id", "created_at", "updated_at", "expires_at", "status",
    )

    def __init__(
        self,
        *,
        memory_id: str,
        user_id: str,
        memory_type: str,
        key: str,
        value: Any,
        source: str,
        confidence: float,
        scope: str,
        scope_order_id: Optional[str] = None,
        session_id: Optional[str] = None,
        created_at: str,
        updated_at: str,
        expires_at: Optional[str] = None,
        status: str = "active",
    ) -> None:
        self.memory_id = memory_id
        self.user_id = user_id
        self.memory_type = memory_type
        self.key = key
        self.value = value
        self.source = source
        self.confidence = confidence
        self.scope = scope
        self.scope_order_id = scope_order_id
        self.session_id = session_id
        self.created_at = created_at
        self.updated_at = updated_at
        self.expires_at = expires_at
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "user_id": self.user_id,
            "memory_type": self.memory_type,
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
            "scope": self.scope,
            "scope_order_id": self.scope_order_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "status": self.status,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "MemoryRecord":
        return cls(
            memory_id=row["memory_id"],
            user_id=row["user_id"],
            memory_type=row["memory_type"],
            key=row["key"],
            value=json.loads(row["value_json"]),
            source=row["source"],
            confidence=row["confidence"],
            scope=row["scope"],
            scope_order_id=row["scope_order_id"],
            session_id=row["session_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            status=row["status"],
        )


class MemoryStore:
    """SQLite-backed Memory 持久化存储。"""

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.db_path = db_path or os.getenv("MEMORY_DB_PATH", "runtime/memory.db")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    scope TEXT NOT NULL,
                    scope_order_id TEXT,
                    session_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active'
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_user_type ON memories(user_id, memory_type, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id, memory_type) WHERE session_id IS NOT NULL"
            )

    def _now(self) -> datetime:
        current = self.clock()
        return current if current.tzinfo else current.replace(tzinfo=timezone.utc)

    def upsert(
        self,
        *,
        user_id: str,
        memory_type: str,
        key: str,
        value: Any,
        source: str,
        confidence: float,
        scope: str = "user",
        scope_order_id: Optional[str] = None,
        session_id: Optional[str] = None,
        ttl_minutes: Optional[int] = None,
    ) -> str:
        """写入或更新一条 Memory。

        如果 (user_id, memory_type, key, scope, scope_order_id, session_id) 已存在，更新它。
        否则插入新记录。
        """
        now = self._now()
        expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat() if ttl_minutes else None

        with self._connect() as conn:
            row = conn.execute(
                """SELECT memory_id FROM memories
                   WHERE user_id=? AND memory_type=? AND key=?
                     AND COALESCE(scope_order_id, '') = COALESCE(?, '')
                     AND COALESCE(session_id, '') = COALESCE(?, '')
                     AND status='active'""",
                (user_id, memory_type, key, scope_order_id, session_id),
            ).fetchone()

            if row:
                memory_id = row["memory_id"]
                conn.execute(
                    """UPDATE memories SET
                       value_json=?, source=?, confidence=?, updated_at=?, expires_at=?
                       WHERE memory_id=?""",
                    (json.dumps(value, ensure_ascii=False), source, confidence, now.isoformat(), expires_at, memory_id),
                )
                return memory_id

            memory_id = f"mem-{now.strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:8]}"
            conn.execute(
                """INSERT INTO memories
                   (memory_id, user_id, memory_type, key, value_json, source, confidence,
                    scope, scope_order_id, session_id, created_at, updated_at, expires_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
                (memory_id, user_id, memory_type, key,
                 json.dumps(value, ensure_ascii=False), source, confidence,
                 scope, scope_order_id, session_id,
                 now.isoformat(), now.isoformat(), expires_at),
            )
            return memory_id

    def deactivate(self, memory_id: str) -> None:
        """将一条 Memory 标记为过期/失效。"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE memories SET status='expired', updated_at=? WHERE memory_id=?",
                (self._now().isoformat(), memory_id),
            )

    def list_by_user(
        self,
        user_id: str,
        *,
        memory_type: Optional[str] = None,
        active_only: bool = True,
    ) -> list[MemoryRecord]:
        """列出用户的所有 Memory。"""
        query = "SELECT * FROM memories WHERE user_id=?"
        params: list[Any] = [user_id]
        if memory_type:
            query += " AND memory_type=?"
            params.append(memory_type)
        if active_only:
            query += " AND status='active'"
        query += " ORDER BY updated_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [MemoryRecord.from_row(r) for r in rows]

    def get_active(
        self,
        *,
        user_id: str,
        memory_type: str,
        key: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> list[MemoryRecord]:
        """获取有效的 Memory 记录。"""
        now_iso = self._now().isoformat()
        query = """SELECT * FROM memories
                   WHERE user_id=? AND memory_type=? AND status='active'
                     AND (expires_at IS NULL OR expires_at > ?)"""
        params: list[Any] = [user_id, memory_type, now_iso]
        if key:
            query += " AND key=?"
            params.append(key)
        if session_id:
            query += " AND session_id=?"
            params.append(session_id)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [MemoryRecord.from_row(r) for r in rows]

    def add_conversation_message(
        self,
        *,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        ttl_minutes: int = 120,
    ) -> str:
        """添加一条对话消息到 Conversation Memory。"""
        now = self._now()
        seq = uuid.uuid4().hex[:12]
        return self.upsert(
            user_id=user_id,
            memory_type="conversation",
            key=f"msg-{seq}",
            value={"role": role, "content": content, "timestamp": now.isoformat()},
            source="conversation",
            confidence=1.0,
            scope="session",
            session_id=session_id,
            ttl_minutes=ttl_minutes,
        )

    def get_conversation_window(
        self,
        *,
        session_id: str,
        user_id: str,
        window_size: int = 10,
    ) -> list[dict[str, Any]]:
        """获取会话的最近 N 条对话消息。"""
        now_iso = self._now().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT value_json FROM memories
                   WHERE user_id=? AND memory_type='conversation' AND session_id=?
                     AND status='active' AND (expires_at IS NULL OR expires_at > ?)
                   ORDER BY rowid DESC LIMIT ?""",
                (user_id, session_id, now_iso, window_size),
            ).fetchall()
        messages = [json.loads(r["value_json"]) for r in reversed(rows)]
        return messages

    def save_conversation_summary(
        self,
        *,
        user_id: str,
        session_id: str,
        summary: str,
        message_count: int,
        ttl_minutes: int = 360,
    ) -> str:
        """保存对话摘要。"""
        return self.upsert(
            user_id=user_id,
            memory_type="conversation_summary",
            key=f"summary-{session_id}",
            value={"summary": summary, "message_count": message_count},
            source="model_summary",
            confidence=0.85,
            scope="session",
            session_id=session_id,
            ttl_minutes=ttl_minutes,
        )

    def get_conversation_summary(
        self,
        *,
        session_id: str,
        user_id: str,
    ) -> Optional[str]:
        """获取会话摘要。"""
        now_iso = self._now().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """SELECT value_json FROM memories
                   WHERE user_id=? AND memory_type='conversation_summary' AND session_id=?
                     AND status='active' AND (expires_at IS NULL OR expires_at > ?)
                   ORDER BY updated_at DESC LIMIT 1""",
                (user_id, session_id, now_iso),
            ).fetchone()
        if not row:
            return None
        return json.loads(row["value_json"]).get("summary")

    def purge_expired(self) -> int:
        """清理过期 Memory。"""
        now_iso = self._now().isoformat()
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE memories SET status='expired', updated_at=? WHERE expires_at IS NOT NULL AND expires_at < ? AND status='active'",
                (now_iso, now_iso),
            )
            return result.rowcount

    def clear_session(self, session_id: str) -> int:
        """清除会话的所有 Conversation Memory。"""
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE memories SET status='expired', updated_at=? WHERE session_id=? AND memory_type IN ('conversation', 'conversation_summary')",
                (self._now().isoformat(), session_id),
            )
            return result.rowcount
