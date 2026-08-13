import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from apps.api.support.responses import ToolResponse

logger = logging.getLogger("ai_support_delivery.tool")


class ReturnApplicationService:
    def __init__(self, orders: Dict[str, Dict[str, Any]]) -> None:
        self.orders = orders
        self.applications: Dict[str, Dict[str, Any]] = {}
        self.keys: Dict[str, str] = {}
        self.sequence = 1

    def submit(self, order_id: str, user_id: str, reason: str, key: str, trace_id: str) -> ToolResponse:
        order = self.orders.get(order_id)
        if order is None:
            return ToolResponse.failure(trace_id, "404_ORDER_NOT_FOUND", "未找到该订单，无法提交退货申请。", 404)
        if order["anonymous_user_id"] != user_id:
            return ToolResponse.failure(trace_id, "403_ORDER_FORBIDDEN", "无权为该订单提交退货申请。", 403)
        if key in self.keys:
            return ToolResponse.success_result(self.applications[self.keys[key]], trace_id, "已返回同一请求创建的退货申请。")

        application_id = f"RA202608{self.sequence:04d}"
        self.sequence += 1
        application = {
            "application_id": application_id,
            "order_id": order_id,
            "reason": reason,
            "status": "待审核",
            "next_steps": ["等待客服审核退货申请。", "审核通过后按指引寄回商品。", "寄回后可在售后渠道查看处理进度。"],
            "notice": "退货申请已提交不代表退款已完成，最终结果以人工审核为准。",
            "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.keys[key] = application_id
        self.applications[application_id] = application
        logger.info("tool_call", extra={"event": "tool_call", "tool_name": "submit_return_application", "trace_id": trace_id, "success": True, "error_code": None})
        return ToolResponse.success_result(application, trace_id, "退货申请已提交，当前状态为待审核。")

    def pending(self) -> list[Dict[str, Any]]:
        """Return applications that are visible to the manual review queue."""
        return [application for application in self.applications.values() if application["status"] == "待审核"]

    def get_for_user(self, application_id: str, user_id: str, trace_id: str) -> ToolResponse:
        application = self.applications.get(application_id)
        if application is None:
            return ToolResponse.failure(trace_id, "404_RETURN_APPLICATION_NOT_FOUND", "未找到该退货申请。", 404)
        order = self.orders.get(application["order_id"])
        if order is None or order["anonymous_user_id"] != user_id:
            return ToolResponse.failure(trace_id, "403_ORDER_FORBIDDEN", "无权查看该退货申请。", 403)
        return ToolResponse.success_result(application, trace_id, "已返回退货申请最新状态。")

    def review(self, application_id: str, reviewer: str, decision: str, reason: Optional[str], trace_id: str) -> ToolResponse:
        application = self.applications.get(application_id)
        if application is None:
            return ToolResponse.failure(trace_id, "404_RETURN_APPLICATION_NOT_FOUND", "未找到该退货申请。", 404)
        if application["status"] != "待审核":
            return ToolResponse.failure(trace_id, "409_RETURN_APPLICATION_ALREADY_REVIEWED", "该退货申请已经审核过，不能重复操作。", 409)
        if decision == "rejected" and not reason:
            return ToolResponse.failure(trace_id, "400_REVIEW_REASON_REQUIRED", "审核不通过时必须填写原因。", 400)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        application["status"] = "审核通过" if decision == "approved" else "审核不通过"
        application["reviewed_at"] = now
        application["reviewer"] = reviewer
        application["review_reason"] = reason or "符合退货规则，审核通过。"
        application["next_steps"] = (["按指引寄回商品。", "寄回后在售后渠道查看处理进度。"] if decision == "approved" else ["如有异议，请补充材料或联系人工客服。"])
        message = "退货申请审核通过，可按指引寄回商品。" if decision == "approved" else "退货申请审核不通过，已记录审核原因。"
        return ToolResponse.success_result(application, trace_id, message)
