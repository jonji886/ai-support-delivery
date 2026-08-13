"""LangGraph workflow for the controlled after-sales support assistant.

The graph owns orchestration state and routing only. Business facts and writes
remain behind the existing validated services, which are injected explicitly.
"""

from dataclasses import dataclass
import re
from typing import Any, Callable, Dict, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from apps.api.schemas import AssistRequest
from apps.api.support.config import INTENT_MIN_CONFIDENCE, INTENT_MIN_MARGIN
from apps.api.support.responses import ToolResponse


class SupportState(TypedDict, total=False):
    request: AssistRequest
    user_id: Optional[str]
    trace_id: str
    normalized_message: str
    session: Optional[Dict[str, Any]]
    effective_order_id: Optional[str]
    previous_intent: Optional[str]
    previous_unresolved: int
    intent: str
    confidence: float
    margin: float
    decision_source: str
    result: ToolResponse
    tool_name: str
    conversation_intent: str
    record_conversation: bool
    session_update: Dict[str, Any]


@dataclass(frozen=True)
class SupportGraphDependencies:
    logistics: Any
    returns: Any
    policies: Any
    tickets: Any
    model: Any
    conversations: Any
    record_tool: Callable[[str, str, ToolResponse], None]
    record_conversation: Callable[[str, str, ToolResponse, Optional[str]], None]
    observability: Any


REQUIRED_GRAPH_NODES = {
    "load_context",
    "classify_intent",
    "low_confidence_handoff",
    "risk_handoff",
    "query_logistics",
    "check_return_eligibility",
    "search_policy",
    "finalize",
}


def _normalize_message(message: str) -> str:
    normalized = re.sub(r"\s+", "", message.lower())
    return normalized.translate(str.maketrans({"貨": "货", "尋": "寻"})).replace("查寻", "查询").replace("物留", "物流")


def _fallback_intent(message: str) -> dict[str, Any]:
    if any(word in message for word in ("银行卡", "收款人", "支付密码", "付款账户", "支付账户", "支付账号", "payment", "bank account")):
        return {"intent": "payment_sensitive", "confidence": 0.99, "margin": 0.5}
    if any(word in message for word in ("投诉", "退款争议", "一直不退", "没收到退款")):
        return {"intent": "complaint", "confidence": 0.99, "margin": 0.5}
    if any(word in message for word in ("物流", "包裹", "到哪里", "到哪了", "运输")):
        return {"intent": "logistics", "confidence": 0.95, "margin": 0.3}
    if any(word in message for word in ("规则", "政策", "时效", "多久可以退")):
        return {"intent": "policy", "confidence": 0.9, "margin": 0.2}
    if any(word in message for word in ("退货", "换货", "能退", "退吗", "想退")):
        return {"intent": "return", "confidence": 0.95, "margin": 0.3}
    return {"intent": "unknown", "confidence": 0.4, "margin": 0.05}


def _extract_return_reason(message: str) -> Optional[str]:
    match = re.search(r"原因\s*[:：]\s*([^）)]+)", message)
    return match.group(1).strip() if match else None


def build_support_graph(deps: SupportGraphDependencies) -> Any:
    """Build the compiled graph with explicit, testable business routes."""

    def load_context(state: SupportState) -> SupportState:
        request = state["request"]
        user_id = state.get("user_id")
        trace_id = state["trace_id"]
        if deps.conversations.session_belongs_to_other_user(request.session_id, user_id):
            return {
                "result": ToolResponse.failure(trace_id, "403_SESSION_FORBIDDEN", "无权访问该会话。", 403),
                "tool_name": "handoff_human",
                "record_conversation": False,
            }
        session = deps.conversations.get(request.session_id, user_id)
        return {
            "normalized_message": _normalize_message(request.message),
            "session": session,
            "effective_order_id": request.order_id or (session or {}).get("order_id"),
            "previous_intent": (session or {}).get("last_intent"),
            "previous_unresolved": int((session or {}).get("unresolved_count", 0)),
        }

    def after_context(state: SupportState) -> str:
        return "finalize" if state.get("result") else "classify_intent"

    def classify_intent(state: SupportState) -> SupportState:
        request = state["request"]
        message = request.message
        normalized = state["normalized_message"]
        previous_intent = state.get("previous_intent")
        follow_up = any(normalized.startswith(prefix) for prefix in ("那", "还", "继续", "然后", "现在", "这个", "它")) or normalized in {"呢", "怎么办", "怎么处理"}
        policy_signal = any(word in normalized for word in ("规则", "政策", "时效", "多久能到", "几天送到", "到货", "发货后", "配送", "shippingpolicy", "returnpolicy"))
        return_signal = any(word in normalized for word in ("退货", "换货", "能退", "退吗", "想退", "iwanttoreturn", "returnthisorder"))
        logistics_signal = any(word in normalized for word in ("物流", "包裹", "到哪里", "到哪了", "运输", "预计", "whereismyorder", "tracking"))
        payment_signal = any(word in message for word in ("银行卡", "收款人", "支付密码", "付款账户", "支付账户", "支付账号", "payment", "bank account"))
        complaint_signal = any(word in message for word in ("投诉", "退款争议", "一直不退", "没收到退款"))
        unsupported_signal = any(word in normalized for word in ("海关税费", "永久退款", "任意商品"))
        explicit_intent = "payment_sensitive" if payment_signal else "complaint" if complaint_signal or unsupported_signal else "policy" if policy_signal else "logistics" if logistics_signal or "订单号" in normalized else "return" if return_signal else None
        if explicit_intent is None and follow_up and previous_intent in {"logistics", "return", "policy"}:
            explicit_intent = previous_intent
        if explicit_intent is None and previous_intent in {"logistics", "return", "policy"} and len(normalized) <= 12:
            explicit_intent = previous_intent
        decision_source = "deterministic_rule"
        if explicit_intent:
            decision = {"intent": explicit_intent, "confidence": 0.99, "margin": 0.5}
        else:
            model_decision = None
            if deps.model.enabled:
                with deps.observability.span("model.deepseek.classify", kind="client", attributes={"model.provider": "deepseek", "model.name": deps.model.model, "model.operation": "intent_classification"}) as model_span:
                    model_decision = deps.model.classify(message, state["trace_id"])
                    model_span.set_result(model_decision is not None, "MODEL_CALL_FAILED" if model_decision is None else None, fallback_used=model_decision is None)
            decision = model_decision or _fallback_intent(message)
            decision_source = "model" if model_decision else "fallback_rule"
        return {
            "intent": decision["intent"],
            "confidence": float(decision["confidence"]),
            "margin": float(decision["margin"]),
            "decision_source": decision_source,
        }

    def route_intent(state: SupportState) -> str:
        if state["confidence"] < INTENT_MIN_CONFIDENCE or state["margin"] < INTENT_MIN_MARGIN or state["intent"] == "unknown":
            return "low_confidence_handoff"
        if state["intent"] in {"complaint", "payment_sensitive"}:
            return "risk_handoff"
        return {
            "logistics": "query_logistics",
            "return": "check_return_eligibility",
            "policy": "search_policy",
        }.get(state["intent"], "search_policy")

    def low_confidence_handoff(state: SupportState) -> SupportState:
        request = state["request"]
        trace_id = state["trace_id"]
        order_id = state.get("effective_order_id")
        with deps.observability.span("tool.create_service_ticket", kind="client", attributes={"tool.name": "create_service_ticket", "tool.operation": "write"}) as tool_span:
            ticket = deps.tickets.create(f"用户诉求：{request.message}", "low_confidence", "high", order_id, f"assist-{trace_id}", trace_id, state.get("user_id"))
            tool_span.set_result(ticket.success, ticket.error_code)
        ticket.data["handoff_reason"] = "意图置信度不足，无法安全确认"
        ticket.data["summary"] = {"user_request": request.message, "order_id": order_id, "actions_taken": [], "handoff_reason": "意图置信度不足，无法安全确认"}
        ticket.message = "目前无法可靠确认您的问题类型，已转人工处理。"
        ticket.handoff = True
        return _outcome(ticket, "handoff_human", "unknown", request, state, intent="unknown", resolved=False)

    def risk_handoff(state: SupportState) -> SupportState:
        request = state["request"]
        trace_id = state["trace_id"]
        intent = state["intent"]
        order_id = state.get("effective_order_id")
        category = "payment_sensitive" if intent == "payment_sensitive" else "complaint_or_dispute"
        reason = "支付敏感问题涉及支付账户或收款信息，必须由人工核验" if intent == "payment_sensitive" else "高风险投诉或退款争议默认转人工"
        with deps.observability.span("tool.create_service_ticket", kind="client", attributes={"tool.name": "create_service_ticket", "tool.operation": "write"}) as tool_span:
            ticket = deps.tickets.create(f"用户诉求：{request.message}", category, "urgent", order_id, f"assist-{trace_id}", trace_id, state.get("user_id"))
            tool_span.set_result(ticket.success, ticket.error_code)
        ticket.data["handoff_reason"] = reason
        ticket.data["summary"] = {"user_request": request.message, "order_id": order_id, "actions_taken": ["识别支付敏感意图" if intent == "payment_sensitive" else "识别高风险意图", "创建售后工单"], "handoff_reason": reason}
        ticket.message = "该问题涉及支付敏感信息，已停止自动处理并创建人工工单。" if intent == "payment_sensitive" else "该问题需要人工处理，已创建售后工单。"
        ticket.handoff = True
        return _outcome(ticket, "create_service_ticket", intent, request, state, intent=intent, resolved=False)

    def query_logistics(state: SupportState) -> SupportState:
        request = state["request"]
        trace_id = state["trace_id"]
        order_id = state.get("effective_order_id")
        user_id = state.get("user_id")
        with deps.observability.span("tool.query_order_logistics", kind="client", attributes={"tool.name": "query_order_logistics", "tool.operation": "read"}) as tool_span:
            result = ToolResponse.failure(trace_id, "400_ORDER_REQUIRED", "请提供订单号并完成身份校验。") if not user_id or not order_id else deps.logistics.query(order_id, user_id, trace_id)
            tool_span.set_result(result.success, result.error_code)
        if result.success:
            logistics = result.data or {}
            latest = logistics.get("latest_event") or {}
            eta = logistics.get("estimated_arrival")
            result.message = f"订单 {logistics.get('order_id', request.order_id)} 当前状态为“{logistics.get('order_status', '未知')}”。最新节点：{latest.get('description', '暂无')}（{latest.get('location', '未知地点')}）。" + (f"预计 {eta} 到达。" if eta else "暂未提供预计到达时间。")
        return _outcome(result, "query_order_logistics", "logistics", request, state, intent="logistics", resolved=result.success)

    def check_return_eligibility(state: SupportState) -> SupportState:
        request = state["request"]
        trace_id = state["trace_id"]
        session = state.get("session") or {}
        reason = request.return_reason or _extract_return_reason(request.message) or session.get("return_reason")
        if not reason and state.get("previous_intent") == "return" and any(word in request.message for word in ("尺码", "质量", "损坏", "不合适", "不喜欢")):
            reason = request.message.strip()
        order_id = state.get("effective_order_id")
        user_id = state.get("user_id")
        with deps.observability.span("tool.check_return_eligibility", kind="client", attributes={"tool.name": "check_return_eligibility", "tool.operation": "read"}) as tool_span:
            result = ToolResponse.failure(trace_id, "400_RETURN_FIELDS_REQUIRED", "要判断退换货资格，请补充订单号和退货原因。示例：OD202608001，原因：尺码不合适。") if not user_id or not order_id or not reason else deps.returns.check(order_id, user_id, reason, trace_id)
            tool_span.set_result(result.success, result.error_code)
        outcome = _outcome(result, "check_return_eligibility", "return", request, state, intent="return", resolved=result.success and not result.handoff, return_reason=reason)
        if not result.success and state.get("previous_unresolved", 0) >= 1:
            # Preserve the failed attempt in the audit trail before replacing
            # the user-facing result with a controlled human handoff.
            deps.record_tool("check_return_eligibility", trace_id, result)
            deps.record_conversation(trace_id, "return", result, request.session_id)
            with deps.observability.span("tool.create_service_ticket", kind="client", attributes={"tool.name": "create_service_ticket", "tool.operation": "write"}) as ticket_span:
                ticket = deps.tickets.create(f"用户连续两次未解决：{request.message}", "low_confidence", "high", order_id, f"assist-{trace_id}", trace_id, user_id)
                ticket_span.set_result(ticket.success, ticket.error_code)
            ticket.data["handoff_reason"] = "同一会话连续两次未解决，转人工处理"
            ticket.message = "连续两次未能完成退货资格判断，已转人工处理。"
            ticket.handoff = True
            outcome.update(_outcome(ticket, "handoff_human", "return", request, state, intent="return", resolved=False, unresolved_count=2))
            outcome["record_conversation"] = False
        return outcome

    def search_policy(state: SupportState) -> SupportState:
        with deps.observability.span("rag.search_policy", kind="client", attributes={"rag.region": "US", "rag.strategy": deps.policies.default_strategy}) as rag_span:
            result = deps.policies.search(state["request"].message, "US", state["trace_id"])
            data = result.data if isinstance(result.data, dict) else {}
            retrieval = data.get("retrieval", {})
            rag_span.set_result(
                result.success,
                result.error_code,
                candidate_count=retrieval.get("candidate_count", 0),
                citation_count=len(data.get("citations", [])),
                rerank_score=retrieval.get("rerank_score"),
                embedding_provider=retrieval.get("embedding_provider"),
                reranker_provider=retrieval.get("reranker_provider"),
            )
        if not result.success:
            result.message = "目前没有可验证的规则依据，建议转人工。"
            result = result.model_copy(update={"http_status": 200})
        elif isinstance(result.data, dict) and result.data.get("answer"):
            result.message = result.data["answer"]
        else:
            result.message = "已根据生效规则并附引用回答。"
        return {
            "result": result,
            "tool_name": "search_policy",
            "conversation_intent": "policy",
            "record_conversation": True,
        }

    def finalize(state: SupportState) -> SupportState:
        result = state["result"]
        deps.record_tool(state["tool_name"], state["trace_id"], result)
        if state.get("record_conversation", True):
            deps.record_conversation(state["trace_id"], state.get("conversation_intent", state.get("intent", "unknown")), result, state["request"].session_id)
        if state.get("session_update"):
            deps.conversations.save(state["request"].session_id, **state["session_update"])
        return {}

    def observed_node(name: str, function: Callable[[SupportState], SupportState]) -> Callable[[SupportState], SupportState]:
        def run(state: SupportState) -> SupportState:
            with deps.observability.span(f"graph.{name}", kind="internal", attributes={"graph.node": name}) as node_span:
                update = function(state)
                node_span.set_attributes(
                    intent=update.get("intent") or state.get("intent"),
                    decision_source=update.get("decision_source"),
                    tool_name=update.get("tool_name"),
                )
                return update
        return run

    workflow = StateGraph(SupportState)
    workflow.add_node("load_context", observed_node("load_context", load_context))
    workflow.add_node("classify_intent", observed_node("classify_intent", classify_intent))
    workflow.add_node("low_confidence_handoff", observed_node("low_confidence_handoff", low_confidence_handoff))
    workflow.add_node("risk_handoff", observed_node("risk_handoff", risk_handoff))
    workflow.add_node("query_logistics", observed_node("query_logistics", query_logistics))
    workflow.add_node("check_return_eligibility", observed_node("check_return_eligibility", check_return_eligibility))
    workflow.add_node("search_policy", observed_node("search_policy", search_policy))
    workflow.add_node("finalize", observed_node("finalize", finalize))
    workflow.add_edge(START, "load_context")
    workflow.add_conditional_edges("load_context", after_context, {"classify_intent": "classify_intent", "finalize": "finalize"})
    workflow.add_conditional_edges("classify_intent", route_intent, {name: name for name in REQUIRED_GRAPH_NODES if name not in {"load_context", "classify_intent", "finalize"}})
    for node in REQUIRED_GRAPH_NODES - {"load_context", "classify_intent", "finalize"}:
        workflow.add_edge(node, "finalize")
    workflow.add_edge("finalize", END)
    return workflow.compile()


def _outcome(result: ToolResponse, tool_name: str, conversation_intent: str, request: AssistRequest, state: SupportState, **session_values: Any) -> SupportState:
    return {
        "result": result,
        "tool_name": tool_name,
        "conversation_intent": conversation_intent,
        "record_conversation": True,
        "session_update": {
            "user_id": state.get("user_id"),
            "order_id": state.get("effective_order_id"),
            **session_values,
        },
    }
