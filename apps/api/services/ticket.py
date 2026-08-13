import logging
from datetime import datetime, timezone
from typing import Any, Optional

from apps.api.support.responses import ToolResponse

logger = logging.getLogger("ai_support_delivery.tool")


class TicketService:
    def __init__(self) -> None:
        self.tickets: dict[str, dict[str, Any]] = {}
        self.keys: dict[str, str] = {}
        self.sequence = 1

    def create(self, summary: str, category: str, priority: str, order_id: Optional[str], key: str, trace_id: str, user_id: Optional[str] = None) -> ToolResponse:
        if key in self.keys:
            ticket = self.tickets[self.keys[key]]
            return ToolResponse.success_result(ticket, trace_id, "已返回同一幂等请求创建的工单。")
        ticket_id = f"TK202608{self.sequence:04d}"
        self.sequence += 1
        ticket = {"ticket_id": ticket_id, "order_id": order_id, "category": category, "priority": priority, "summary": summary, "status": "待人工处理", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "user_id": user_id}
        self.keys[key] = ticket_id
        self.tickets[ticket_id] = ticket
        logger.info("tool_call", extra={"event": "tool_call", "tool_name": "create_service_ticket", "trace_id": trace_id, "ticket_id": ticket_id, "success": True, "error_code": None})
        return ToolResponse.success_result(ticket, trace_id, "已创建售后工单。")

    def list_tickets(self) -> list[dict[str, Any]]:
        return list(self.tickets.values())

    def get_for_user(self, ticket_id: str, user_id: str, trace_id: str) -> ToolResponse:
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            return ToolResponse.failure(trace_id, "404_TICKET_NOT_FOUND", "未找到该售后工单。", 404)
        if ticket.get("user_id") and ticket["user_id"] != user_id:
            return ToolResponse.failure(trace_id, "403_TICKET_FORBIDDEN", "无权查看该售后工单。", 403)
        return ToolResponse.success_result(ticket, trace_id, "已返回工单最新处理状态。")

    def resolve(self, ticket_id: str, status: str, reply: str, trace_id: str) -> ToolResponse:
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            return ToolResponse.failure(trace_id, "404_TICKET_NOT_FOUND", "未找到该售后工单。", 404)
        if ticket["status"] != "待人工处理":
            return ToolResponse.failure(trace_id, "409_TICKET_ALREADY_PROCESSED", "该工单已经处理，不能重复更新。", 409)
        ticket.update({"status": status, "agent_reply": reply, "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        return ToolResponse.success_result(ticket, trace_id, "工单处理结果已保存。")
