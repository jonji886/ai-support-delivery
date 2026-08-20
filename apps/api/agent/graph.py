"""LangGraph workflow for the controlled after-sales support assistant.

The graph owns orchestration state and routing only. Business facts and writes
remain behind the existing validated services, which are injected explicitly.
"""

from dataclasses import dataclass
import re
from typing import Any, Callable, Dict, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from apps.api.schemas import AssistRequest
from apps.api.skills.contracts import SkillExecutionContext, SkillResult
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
    secondary_intents: list[str]
    risk_labels: list[str]
    catalog_version: str
    skill_id: str
    skill_version: str
    skill_status: str
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
    intents: Any
    skills: Any
    skill_executor: Any
    skill_handlers: Any


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
        if request.order_id and session and session.get("order_id") and request.order_id != session["order_id"]:
            # Explicit request data has higher authority than inherited memory.
            # Do not let old order-scoped slots influence the switching turn.
            session = dict(session)
            session["return_reason"] = None
            session["slots"] = {
                name: slot for name, slot in (session.get("slots") or {}).items()
                if slot.get("scope") != "order"
            }
            session["last_intent"] = None
            session["unresolved_count"] = 0
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
        previous_intent = state.get("previous_intent")
        decision = deps.intents.classify(message, previous_intent)
        decision_source = decision["source"]
        if decision["intent"] == "unknown":
            model_decision = None
            if deps.model.enabled:
                with deps.observability.span("model.deepseek.classify", kind="client", attributes={"model.provider": "deepseek", "model.name": deps.model.model, "model.operation": "intent_classification"}) as model_span:
                    model_decision = deps.model.classify(message, state["trace_id"])
                    model_span.set_result(model_decision is not None, "MODEL_CALL_FAILED" if model_decision is None else None, fallback_used=model_decision is None)
            if model_decision and deps.intents.is_known(model_decision["intent"]):
                decision = {
                    **decision,
                    **model_decision,
                    "secondary_intents": [],
                    "risk_labels": deps.intents.get(model_decision["intent"])["risk_labels"],
                    "catalog_version": deps.intents.version,
                }
                decision_source = "model_catalog_constrained"
        return {
            "intent": decision["intent"],
            "confidence": float(decision["confidence"]),
            "margin": float(decision["margin"]),
            "decision_source": decision_source,
            "secondary_intents": decision.get("secondary_intents", []),
            "risk_labels": decision.get("risk_labels", []),
            "catalog_version": decision.get("catalog_version", deps.intents.version),
            "skill_id": deps.skills.for_intent(decision["intent"]).skill_id,
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
        return _run_skill(state, "risk_handoff", "low_confidence_handoff", deps.skill_handlers.risk_handoff)

    def risk_handoff(state: SupportState) -> SupportState:
        return _run_skill(state, "risk_handoff", "risk_handoff", deps.skill_handlers.risk_handoff)

    def query_logistics(state: SupportState) -> SupportState:
        return _run_skill(state, "logistics_inquiry", "query", deps.skill_handlers.logistics_inquiry)

    def check_return_eligibility(state: SupportState) -> SupportState:
        return _run_skill(state, "return_resolution", "eligibility_check", deps.skill_handlers.return_resolution)

    def search_policy(state: SupportState) -> SupportState:
        return _run_skill(state, "policy_qa", "retrieve_and_answer", deps.skill_handlers.policy_qa)

    def _run_skill(state: SupportState, skill_id: str, phase: str, handler: Any) -> SupportState:
        payload = {
            "request": state["request"],
            "user_id": state.get("user_id"),
            "session": state.get("session"),
            "effective_order_id": state.get("effective_order_id"),
            "previous_intent": state.get("previous_intent"),
            "previous_unresolved": state.get("previous_unresolved", 0),
            "secondary_intents": state.get("secondary_intents", []),
            "risk_labels": state.get("risk_labels", []),
            "catalog_version": state.get("catalog_version"),
        }
        skill_result = deps.skill_executor.execute(
            skill_id,
            SkillExecutionContext(
                trace_id=state["trace_id"], intent=state.get("intent", "unknown"),
                phase=phase, payload=payload,
            ),
            handler,
        )
        return _skill_outcome(skill_result, state["request"], state)

    def finalize(state: SupportState) -> SupportState:
        result = state["result"]
        intent = state.get("conversation_intent", state.get("intent", "unknown"))
        if not deps.intents.is_tool_allowed(intent, state["tool_name"]):
            result = ToolResponse.failure(
                state["trace_id"], "500_INTENT_TOOL_POLICY_VIOLATION",
                "意图与 Tool 权限策略冲突，已停止自动处理。", 500,
            )
            state["result"] = result
        deps.record_tool(state["tool_name"], state["trace_id"], result)
        if state.get("record_conversation", True):
            deps.record_conversation(state["trace_id"], state.get("conversation_intent", state.get("intent", "unknown")), result, state["request"].session_id)
        if state.get("session_update") and state["session_update"].get("intent"):
            deps.conversations.save(state["request"].session_id, **state["session_update"])
        return {}

    def observed_node(name: str, function: Callable[[SupportState], SupportState]) -> Callable[[SupportState], SupportState]:
        def run(state: SupportState) -> SupportState:
            with deps.observability.span(f"graph.{name}", kind="internal", attributes={"graph.node": name}) as node_span:
                update = function(state)
                node_span.set_attributes(
                    intent=update.get("intent") or state.get("intent"),
                    decision_source=update.get("decision_source"),
                    catalog_version=update.get("catalog_version"),
                    secondary_intents=update.get("secondary_intents"),
                    risk_labels=update.get("risk_labels"),
                    skill_id=update.get("skill_id") or state.get("skill_id"),
                    skill_version=update.get("skill_version"),
                    skill_status=update.get("skill_status"),
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


def _skill_outcome(outcome: SkillResult, request: AssistRequest, state: SupportState) -> SupportState:
    update = _outcome(
        outcome.result, outcome.tool_name, outcome.intent, request, state,
        **outcome.session_values,
    )
    update.update({
        "skill_id": outcome.skill_id,
        "skill_version": outcome.skill_version,
        "skill_status": outcome.status,
        "record_conversation": outcome.record_conversation,
    })
    return update


def _outcome(result: ToolResponse, tool_name: str, conversation_intent: str, request: AssistRequest, state: SupportState, **session_values: Any) -> SupportState:
    slot_sources = dict(session_values.pop("slot_sources", {}))
    if request.order_id:
        previous_order_id = (state.get("session") or {}).get("order_id")
        slot_sources["order_id"] = "user_correction" if previous_order_id and previous_order_id != request.order_id else "user_explicit"
    elif state.get("effective_order_id"):
        slot_sources["order_id"] = "conversation_inherited"
    if request.return_reason or _extract_return_reason(request.message):
        slot_sources["return_reason"] = "user_explicit"
    elif session_values.get("return_reason"):
        slot_sources["return_reason"] = "conversation_inherited"
    verified_facts = session_values.pop("verified_facts", {})
    if result.success and tool_name == "query_order_logistics":
        verified_facts["logistics"] = result.data
    if result.success and tool_name == "check_return_eligibility":
        verified_facts["return"] = result.data
    return {
        "result": result,
        "tool_name": tool_name,
        "conversation_intent": conversation_intent,
        "record_conversation": True,
        "session_update": {
            "user_id": state.get("user_id"),
            "order_id": state.get("effective_order_id"),
            "slot_sources": slot_sources,
            "verified_facts": verified_facts,
            **session_values,
        },
    }
