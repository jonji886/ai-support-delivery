import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from apps.api.schemas import ReturnEligibilityData
from apps.api.support.responses import ToolResponse

logger = logging.getLogger("ai_support_delivery.tool")


class ReturnEligibilityService:
    def __init__(
        self,
        orders: dict[str, dict[str, Any]],
        policies: dict[str, dict[str, Any]],
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.orders = orders
        self.policies = policies
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def from_default_data(cls) -> "ReturnEligibilityService":
        data_root = Path(__file__).parents[3] / "data" / "mock"
        with (data_root / "orders.json").open(encoding="utf-8") as file:
            orders = {item["order_id"]: item for item in json.load(file)}
        with (data_root / "policies" / "return-policy.json").open(encoding="utf-8") as file:
            policies = {item["category"]: item for item in json.load(file)}
        return cls(orders, policies)

    def check(self, order_id: str, user_id: str, reason: str, trace_id: str) -> ToolResponse:
        started_at = self.clock().timestamp()
        order = self.orders.get(order_id)
        if order is None:
            return self._failure(trace_id, "404_ORDER_NOT_FOUND", "未找到该订单，无法判断退换货资格。", 404, started_at)
        if order["anonymous_user_id"] != user_id:
            return self._failure(trace_id, "403_ORDER_FORBIDDEN", "无权查询该订单。", 403, started_at)
        if order.get("order_status") not in {"已签收", "已完成"} or not order.get("signed_at"):
            return self._failure(trace_id, "409_ORDER_STATUS_UNSUPPORTED", "订单状态或签收信息异常，需要人工核实。", 409, started_at)

        if self._is_high_risk_reason(reason):
            return self._decision(
                trace_id, order_id, False, "human_review", "当前原因涉及商品质量或争议，需要人工审核。",
                ["请保留商品照片和相关凭证，等待人工客服审核。"], True, started_at,
            )

        policy = self.policies.get(order.get("category"))
        if policy is None:
            return self._failure(trace_id, "424_POLICY_NOT_FOUND", "未找到适用的退换货规则，需要人工核实。", 424, started_at)

        signed_at = datetime.fromisoformat(order["signed_at"].replace("Z", "+00:00"))
        days_since_signed = (self.clock() - signed_at).days
        eligible = days_since_signed <= policy["return_window_days"]
        if eligible:
            basis = f"签收后第 {days_since_signed} 天，未超过 {policy['return_window_days']} 天退货期限。"
            next_steps = ["在售后页面提交退货申请。", "保持商品及包装完好，并按页面指引寄回。"]
            decision = "eligible"
        else:
            basis = f"签收后第 {days_since_signed} 天，已超过 {policy['return_window_days']} 天退货期限。"
            next_steps = ["该情况需要人工客服核实是否存在特殊例外。"]
            decision = "expired"
        return self._decision(trace_id, order_id, eligible, decision, basis, next_steps, not eligible, started_at, policy["version"])

    @staticmethod
    def _is_high_risk_reason(reason: str) -> bool:
        return any(keyword in reason for keyword in ("质量", "损坏", "欺诈", "退款争议", "投诉"))

    def _decision(self, trace_id: str, order_id: str, eligible: bool, decision: str, basis: str, next_steps: list[str], requires_human: bool, started_at: float, rule_version: str = "return-policy-v1") -> ToolResponse:
        data = ReturnEligibilityData(
            order_id=order_id, eligible=eligible, decision=decision, rule_version=rule_version,
            basis=basis, next_steps=next_steps, requires_human=requires_human,
        )
        logger.info("tool_call", extra={"event": "tool_call", "tool_name": "check_return_eligibility", "trace_id": trace_id, "order_id": order_id, "success": True, "error_code": None, "duration_ms": round((self.clock().timestamp() - started_at) * 1000, 2)})
        message = "符合退货条件，可提交退货申请。" if eligible else "当前不符合自动退货条件，需要人工核实。"
        if requires_human:
            message = "该退货原因需要人工审核，暂不自动批准。"
        return ToolResponse.success_result(data.model_dump(mode="json"), trace_id, message)

    @staticmethod
    def _failure(trace_id: str, code: str, message: str, status: int, started_at: float) -> ToolResponse:
        logger.info("tool_call", extra={"event": "tool_call", "tool_name": "check_return_eligibility", "trace_id": trace_id, "order_id": None, "success": False, "error_code": code, "duration_ms": 0})
        return ToolResponse.failure(trace_id, code, message, status)
