import logging
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from apps.api.support.errors import IntegrationError
from apps.api.support.integration import IntegrationAdapter, map_to_tool_error_code
from apps.api.support.responses import ToolResponse

logger = logging.getLogger("ai_support_delivery.tool")


class TicketService:
    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        adapter: Optional[IntegrationAdapter] = None,
    ) -> None:
        self.db_path = db_path or os.getenv("SUPPORT_DB_PATH", "runtime/support.db")
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._initialize()
        self.adapter = adapter or IntegrationAdapter(system="ticket", max_retries=0)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    user_id TEXT,
                    order_id TEXT,
                    category TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    agent_reply TEXT,
                    resolved_at TEXT
                )"""
            )
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_idempotency ON tickets(idempotency_key)")

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    def _next_id(self, connection: sqlite3.Connection) -> str:
        row = connection.execute("SELECT COUNT(*) AS count FROM tickets").fetchone()
        return f"TK202608{int(row['count']) + 1:04d}"

    def create(self, summary: str, category: str, priority: str, order_id: Optional[str], key: str, trace_id: str, user_id: Optional[str] = None) -> ToolResponse:
        def _do_create() -> ToolResponse:
            created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with self._connect() as connection:
                existing = connection.execute("SELECT * FROM tickets WHERE idempotency_key = ?", (key,)).fetchone()
                if existing:
                    if existing["user_id"] != user_id:
                        return ToolResponse.failure(trace_id, "409_IDEMPOTENCY_KEY_CONFLICT", "幂等键已被其他用户使用，不能复用。", 409)
                    return ToolResponse.success_result(self._row(existing), trace_id, "已返回同一幂等请求创建的工单。")
                ticket_id = self._next_id(connection)
                connection.execute(
                    """INSERT INTO tickets
                    (ticket_id, idempotency_key, user_id, order_id, category, priority, summary, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ticket_id, key, user_id, order_id, category, priority, summary, "待人工处理", created_at),
                )
                ticket = self._row(connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone())
            logger.info("tool_call", extra={"event": "tool_call", "tool_name": "create_service_ticket", "trace_id": trace_id, "ticket_id": ticket_id, "success": True, "error_code": None})
            return ToolResponse.success_result(ticket, trace_id, "已创建售后工单。")

        try:
            # Write operations are not retried automatically; idempotency key
            # protects against duplicate submission if the caller retries.
            return self.adapter.call(_do_create, read_only=False)
        except IntegrationError as exc:
            code, status, handoff = map_to_tool_error_code(exc)
            return ToolResponse.failure(trace_id, code, str(exc), status, handoff=handoff)

    def list_tickets(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> dict[str, Any]:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        conditions = []
        values: list[Any] = []
        if keyword:
            conditions.append("(ticket_id LIKE ? OR summary LIKE ? OR order_id LIKE ?)")
            pattern = f"%{keyword}%"
            values.extend([pattern, pattern, pattern])
        if status:
            conditions.append("status = ?")
            values.append(status)
        if category:
            conditions.append("category = ?")
            values.append(category)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as connection:
            total = connection.execute(f"SELECT COUNT(*) AS count FROM tickets {where}", values).fetchone()["count"]
            offset = (page - 1) * page_size
            rows = connection.execute(
                f"SELECT * FROM tickets {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*values, page_size, offset],
            )
            return {"items": [self._row(row) for row in rows], "page": page, "page_size": page_size, "total": total}

    def get_for_user(self, ticket_id: str, user_id: str, trace_id: str) -> ToolResponse:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if row is None:
            return ToolResponse.failure(trace_id, "404_TICKET_NOT_FOUND", "未找到该售后工单。", 404)
        ticket = self._row(row)
        if not ticket.get("user_id") or ticket["user_id"] != user_id:
            return ToolResponse.failure(trace_id, "403_TICKET_FORBIDDEN", "无权查看该售后工单。", 403)
        return ToolResponse.success_result(ticket, trace_id, "已返回工单最新处理状态。")

    def resolve(self, ticket_id: str, status: str, reply: str, trace_id: str) -> ToolResponse:
        resolved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
            if row is None:
                return ToolResponse.failure(trace_id, "404_TICKET_NOT_FOUND", "未找到该售后工单。", 404)
            if row["status"] != "待人工处理":
                return ToolResponse.failure(trace_id, "409_TICKET_ALREADY_PROCESSED", "该工单已经处理，不能重复更新。", 409)
            connection.execute("UPDATE tickets SET status = ?, agent_reply = ?, resolved_at = ? WHERE ticket_id = ? AND status = ?", (status, reply, resolved_at, ticket_id, "待人工处理"))
            ticket = self._row(connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone())
        return ToolResponse.success_result(ticket, trace_id, "工单处理结果已保存。")
