import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from apps.api.skills.contracts import SkillExecutionContext, SkillResult
from apps.api.support.responses import ToolResponse


def _extract_return_reason(message: str) -> Optional[str]:
    match = re.search(r"原因\s*[:：]\s*([^）)]+)", message)
    return match.group(1).strip() if match else None


@dataclass(frozen=True)
class SkillHandlerDependencies:
    logistics: Any
    returns: Any
    return_applications: Any
    policies: Any
    tickets: Any
    record_tool: Callable[[str, str, ToolResponse], None]
    record_conversation: Callable[[str, str, ToolResponse, Optional[str]], None]


class SupportSkillHandlers:
    def __init__(self, deps: SkillHandlerDependencies) -> None:
        self.deps = deps

    def logistics_inquiry(self, context: SkillExecutionContext, tools: Any) -> SkillResult:
        payload = context.payload
        request = payload["request"]
        order_id = payload.get("effective_order_id")
        user_id = payload.get("user_id")
        missing = tools.missing_slots({"user_id": user_id, "order_id": order_id})
        result = (
            ToolResponse.failure(context.trace_id, "400_ORDER_REQUIRED", "请提供订单号并完成身份校验。")
            if missing
            else tools.call(
                "query_order_logistics", "read",
                lambda: self.deps.logistics.query(order_id, user_id, context.trace_id),
            )
        )
        if result.success:
            logistics = result.data or {}
            latest = logistics.get("latest_event") or {}
            eta = logistics.get("estimated_arrival")
            result.message = (
                f"订单 {logistics.get('order_id', request.order_id)} 当前状态为“{logistics.get('order_status', '未知')}”。"
                f"最新节点：{latest.get('description', '暂无')}（{latest.get('location', '未知地点')}）。"
                + (f"预计 {eta} 到达。" if eta else "暂未提供预计到达时间。")
            )
        return SkillResult.from_tool(
            "logistics_inquiry", "logistics", "query_order_logistics", result,
            status="needs_input" if missing else None,
            missing_slots=missing,
            session_values={"intent": "logistics", "resolved": result.success},
        )

    def return_resolution(self, context: SkillExecutionContext, tools: Any) -> SkillResult:
        if context.phase == "confirm_submit":
            return self._submit_return(context, tools)
        payload = context.payload
        request = payload["request"]
        session = payload.get("session") or {}
        reason = request.return_reason or _extract_return_reason(request.message) or session.get("return_reason")
        if not reason and payload.get("previous_intent") == "return" and any(
            word in request.message for word in ("尺码", "质量", "损坏", "不合适", "不喜欢")
        ):
            reason = request.message.strip()
        order_id = payload.get("effective_order_id")
        user_id = payload.get("user_id")
        missing = tools.missing_slots({"user_id": user_id, "order_id": order_id, "return_reason": reason})
        result = (
            ToolResponse.failure(
                context.trace_id, "400_RETURN_FIELDS_REQUIRED",
                "要判断退换货资格，请补充订单号和退货原因。示例：OD202608001，原因：尺码不合适。",
            )
            if missing
            else tools.call(
                "check_return_eligibility", "read",
                lambda: self.deps.returns.check(order_id, user_id, reason, context.trace_id),
            )
        )
        requires_human = bool(isinstance(result.data, dict) and result.data.get("requires_human"))
        if requires_human:
            # The atomic eligibility Tool completed successfully, but the
            # business Skill did not resolve the user's request.
            result = result.model_copy(update={"handoff": True})
        session_values = {
            "intent": "return",
            "resolved": result.success and not result.handoff and not requires_human,
            "return_reason": reason,
        }
        if not result.success and payload.get("previous_unresolved", 0) >= 1:
            self.deps.record_tool("check_return_eligibility", context.trace_id, result)
            self.deps.record_conversation(context.trace_id, "return", result, request.session_id)
            ticket = tools.call(
                "create_service_ticket", "write",
                lambda: self.deps.tickets.create(
                    f"用户连续两次未解决：{request.message}", "low_confidence", "high", order_id,
                    f"assist-{context.trace_id}", context.trace_id, user_id,
                ),
            )
            ticket.data["handoff_reason"] = "同一会话连续两次未解决，转人工处理"
            ticket.message = "连续两次未能完成退货资格判断，已转人工处理。"
            ticket.handoff = True
            return SkillResult.from_tool(
                "return_resolution", "return", "handoff_human", ticket, status="handoff",
                session_values={**session_values, "resolved": False, "unresolved_count": 2},
                record_conversation=False,
            )
        eligible = bool(isinstance(result.data, dict) and result.data.get("eligible"))
        next_actions = ["confirm_return_application"] if result.success and eligible and not requires_human else []
        return SkillResult.from_tool(
            "return_resolution", "return", "check_return_eligibility", result,
            status="needs_input" if missing else "handoff" if requires_human else None,
            missing_slots=missing, next_actions=next_actions, session_values=session_values,
        )

    def _submit_return(self, context: SkillExecutionContext, tools: Any) -> SkillResult:
        payload = context.payload
        required = ("order_id", "user_id", "return_reason", "idempotency_key")
        missing = [name for name in required if not payload.get(name)]
        if missing:
            result = ToolResponse.failure(
                context.trace_id, "400_RETURN_FIELDS_REQUIRED",
                "提交退货申请需要订单号、用户身份、退货原因和幂等键。", handoff=False,
            )
        else:
            result = tools.call(
                "submit_return_application", "write",
                lambda: self.deps.return_applications.submit(
                    payload["order_id"], payload["user_id"], payload["return_reason"],
                    payload["idempotency_key"], context.trace_id,
                ),
            )
        return SkillResult.from_tool(
            "return_resolution", "return", "submit_return_application", result,
            status="needs_input" if missing else None,
            missing_slots=missing,
        )

    def policy_qa(self, context: SkillExecutionContext, tools: Any) -> SkillResult:
        payload = context.payload
        request = payload["request"]
        result = tools.call(
            "search_policy", "read",
            lambda: self.deps.policies.search(request.message, payload.get("region", "US"), context.trace_id),
            span_name="rag.search_policy",
            attributes={"rag.region": payload.get("region", "US"), "rag.strategy": self.deps.policies.default_strategy},
        )
        if not result.success:
            result.message = "目前没有可验证的规则依据，建议转人工。"
            result = result.model_copy(update={"http_status": 200})
        elif isinstance(result.data, dict) and result.data.get("answer"):
            result.message = result.data["answer"]
        else:
            result.message = "已根据生效规则并附引用回答。"
        return SkillResult.from_tool(
            "policy_qa", "policy", "search_policy", result,
            session_values={"intent": "policy", "resolved": result.success and not result.handoff},
        )

    def risk_handoff(self, context: SkillExecutionContext, tools: Any) -> SkillResult:
        payload = context.payload
        request = payload["request"]
        order_id = payload.get("effective_order_id")
        intent = context.intent
        low_confidence = context.phase == "low_confidence_handoff" or intent == "unknown"
        category = "low_confidence" if low_confidence else "payment_sensitive" if intent == "payment_sensitive" else "complaint_or_dispute"
        priority = "high" if low_confidence else "urgent"
        reason = (
            "意图置信度不足，无法安全确认" if low_confidence
            else "支付敏感问题涉及支付账户或收款信息，必须由人工核验" if intent == "payment_sensitive"
            else "高风险投诉或退款争议默认转人工"
        )
        tool_name = "handoff_human" if low_confidence else "create_service_ticket"
        ticket = tools.call(
            tool_name, "write",
            lambda: self.deps.tickets.create(
                f"用户诉求：{request.message}", category, priority, order_id,
                f"assist-{context.trace_id}", context.trace_id, payload.get("user_id"),
            ),
        )
        ticket.data["handoff_reason"] = reason
        actions = [] if low_confidence else ["识别支付敏感意图" if intent == "payment_sensitive" else "识别高风险意图", "创建售后工单"]
        ticket.data["summary"] = {
            "user_request": request.message,
            "order_id": order_id,
            "actions_taken": actions,
            "handoff_reason": reason,
            "secondary_intents": payload.get("secondary_intents", []),
            "risk_labels": payload.get("risk_labels", []),
            "intent_catalog_version": payload.get("catalog_version"),
        }
        ticket.message = (
            "目前无法可靠确认您的问题类型，已转人工处理。" if low_confidence
            else "该问题涉及支付敏感信息，已停止自动处理并创建人工工单。" if intent == "payment_sensitive"
            else "该问题需要人工处理，已创建售后工单。"
        )
        ticket.handoff = True
        return SkillResult.from_tool(
            "risk_handoff", intent, tool_name, ticket, status="handoff",
            session_values={"intent": intent, "resolved": False},
        )
