"""MVP API entrypoint for the controlled order/logistics tool."""

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import re

from apps.api.schemas import AssistRequest, CheckReturnEligibilityRequest, CreateServiceTicketRequest, HandoffHumanRequest, QueryOrderLogisticsRequest, SearchPolicyRequest, SubmitReturnApplicationRequest, ReviewReturnApplicationRequest, ResolveTicketRequest
from apps.api.services.order_logistics import OrderLogisticsService
from apps.api.services.policy_search import PolicySearchService
from apps.api.services.return_eligibility import ReturnEligibilityService
from apps.api.services.ticket import TicketService
from apps.api.services.return_application import ReturnApplicationService
from apps.api.services.deepseek import DeepSeekClient
from apps.api.support.responses import ToolResponse, new_trace_id
from apps.api.support.events import EventStore
from apps.api.support.conversations import ConversationStore
from apps.api.support.config import INTENT_MIN_CONFIDENCE, INTENT_MIN_MARGIN

app = FastAPI(title="AI Support Delivery API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-User-Id", "X-Role"],
)
service = OrderLogisticsService.from_default_data()
return_service = ReturnEligibilityService.from_default_data()
policy_service = PolicySearchService.from_default_data()
ticket_service = TicketService()
return_application_service = ReturnApplicationService(return_service.orders)
deepseek = DeepSeekClient()
events = EventStore()
conversations = ConversationStore()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def record_conversation(trace_id: str, intent: str, result: ToolResponse, session_id: Optional[str] = None) -> None:
    events.append(
        event_type="conversation", trace_id=trace_id, session_id=session_id or trace_id, intent=intent,
        success=result.success, handoff=result.handoff,
        error_code=result.error_code,
        citations=bool(isinstance(result.data, dict) and result.data.get("citations")),
    )


def record_tool(tool_name: str, trace_id: str, result: ToolResponse) -> None:
    events.append(event_type="tool", tool_name=tool_name, trace_id=trace_id, success=result.success, error_code=result.error_code)


@app.post("/tools/query-order-logistics")
def query_order_logistics(
    request: QueryOrderLogisticsRequest,
    x_user_id: Optional[str] = Header(default=None),
) -> JSONResponse:
    trace_id = new_trace_id()
    if not x_user_id:
        result = ToolResponse.failure(
            trace_id=trace_id,
            error_code="401_MISSING_USER",
            message="缺少用户身份，无法查询订单。",
        )
    else:
        result = service.query(request.order_id, x_user_id, trace_id)
    events.append(event_type="tool", tool_name="query_order_logistics", trace_id=trace_id, success=result.success, error_code=result.error_code)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.post("/tools/check-return-eligibility")
def check_return_eligibility(
    request: CheckReturnEligibilityRequest,
    x_user_id: Optional[str] = Header(default=None),
) -> JSONResponse:
    trace_id = new_trace_id()
    if not x_user_id:
        result = ToolResponse.failure(trace_id, "401_MISSING_USER", "缺少用户身份，无法判断退换货资格。")
    else:
        result = return_service.check(request.order_id, x_user_id, request.return_reason, trace_id)
    events.append(event_type="tool", tool_name="check_return_eligibility", trace_id=trace_id, success=result.success, error_code=result.error_code)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.post("/tools/search-policy")
def search_policy(request: SearchPolicyRequest) -> JSONResponse:
    trace_id = new_trace_id()
    result = policy_service.search(request.question, request.region, trace_id)
    events.append(event_type="tool", tool_name="search_policy", trace_id=trace_id, success=result.success, error_code=result.error_code)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.post("/tools/create-service-ticket")
def create_service_ticket(request: CreateServiceTicketRequest) -> JSONResponse:
    trace_id = new_trace_id()
    result = ticket_service.create(
        request.conversation_summary, request.category, request.priority,
        request.order_id, request.idempotency_key, trace_id,
    )
    events.append(event_type="tool", tool_name="create_service_ticket", trace_id=trace_id, success=result.success, error_code=result.error_code)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.post("/tools/handoff-human")
def handoff_human(request: HandoffHumanRequest) -> JSONResponse:
    trace_id = new_trace_id()
    result = ticket_service.create(
        request.conversation_summary, request.category, request.priority,
        request.order_id, request.idempotency_key, trace_id,
    )
    if result.success:
        result.data["handoff_reason"] = request.reason
        result.data["handoff"] = True
        result.message = "已生成客服接管摘要。"
        result.handoff = True
    events.append(event_type="tool", tool_name="handoff_human", trace_id=trace_id, success=result.success, error_code=result.error_code, handoff=True)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.get("/tools/tickets/{ticket_id}")
def get_ticket_for_user(ticket_id: str, x_user_id: Optional[str] = Header(default=None)) -> JSONResponse:
    trace_id = new_trace_id()
    if not x_user_id:
        result = ToolResponse.failure(trace_id, "401_MISSING_USER", "缺少用户身份，无法查询人工处理进度。")
    else:
        result = ticket_service.get_for_user(ticket_id, x_user_id, trace_id)
    record_tool("get_service_ticket", trace_id, result)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.post("/tools/submit-return-application")
def submit_return_application(request: SubmitReturnApplicationRequest, x_user_id: Optional[str] = Header(default=None)) -> JSONResponse:
    trace_id = new_trace_id()
    if not x_user_id:
        result = ToolResponse.failure(trace_id, "401_MISSING_USER", "缺少用户身份，无法提交退货申请。")
    else:
        result = return_application_service.submit(request.order_id, x_user_id, request.return_reason, request.idempotency_key, trace_id)
    record_tool("submit_return_application", trace_id, result)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.get("/agent/return-applications")
def agent_return_applications(x_role: Optional[str] = Header(default=None)) -> JSONResponse:
    """Return the manual review queue for customer-service roles."""
    if x_role not in {"agent", "supervisor", "implementer"}:
        return JSONResponse(status_code=403, content={"success": False, "error_code": "403_ROLE_FORBIDDEN", "message": "需要人工客服、主管或实施人员角色。"})
    return JSONResponse(status_code=200, content={"applications": return_application_service.pending()})


@app.get("/tools/return-applications/{application_id}")
def get_return_application(application_id: str, x_user_id: Optional[str] = Header(default=None)) -> JSONResponse:
    trace_id = new_trace_id()
    if not x_user_id:
        result = ToolResponse.failure(trace_id, "401_MISSING_USER", "缺少用户身份，无法查询退货申请。")
    else:
        result = return_application_service.get_for_user(application_id, x_user_id, trace_id)
    record_tool("get_return_application", trace_id, result)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.post("/agent/return-applications/{application_id}/review")
def review_return_application(application_id: str, request: ReviewReturnApplicationRequest, x_role: Optional[str] = Header(default=None)) -> JSONResponse:
    trace_id = new_trace_id()
    if x_role not in {"agent", "supervisor"}:
        result = ToolResponse.failure(trace_id, "403_ROLE_FORBIDDEN", "只有人工客服或主管可以审核退货申请。", 403)
    else:
        result = return_application_service.review(application_id, x_role, request.decision, request.reason, trace_id)
    record_tool("review_return_application", trace_id, result)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.get("/agent/tickets")
def agent_tickets(x_role: Optional[str] = Header(default=None)) -> JSONResponse:
    if x_role not in {"agent", "supervisor", "implementer"}:
        return JSONResponse(status_code=403, content={"success": False, "error_code": "403_ROLE_FORBIDDEN", "message": "需要客服、主管或实施人员角色。"})
    return JSONResponse(status_code=200, content={"tickets": ticket_service.list_tickets()})


@app.post("/agent/tickets/{ticket_id}/resolve")
def resolve_ticket(ticket_id: str, request: ResolveTicketRequest, x_role: Optional[str] = Header(default=None)) -> JSONResponse:
    trace_id = new_trace_id()
    if x_role not in {"agent", "supervisor"}:
        result = ToolResponse.failure(trace_id, "403_ROLE_FORBIDDEN", "只有人工客服或主管可以处理工单。", 403)
    else:
        result = ticket_service.resolve(ticket_id, request.status, request.reply, trace_id)
    record_tool("resolve_service_ticket", trace_id, result)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.post("/assist")
def assist(request: AssistRequest, x_user_id: Optional[str] = Header(default=None)) -> JSONResponse:
    """DeepSeek classifies intent when configured; tools remain the source of truth."""
    trace_id = new_trace_id()
    message = request.message
    normalized_message = re.sub(r"\s+", "", message.lower())
    if conversations.session_belongs_to_other_user(request.session_id, x_user_id):
        result = ToolResponse.failure(trace_id, "403_SESSION_FORBIDDEN", "无权访问该会话。", 403)
        record_tool("handoff_human", trace_id, result)
        return JSONResponse(status_code=403, content=result.model_dump())
    session = conversations.get(request.session_id, x_user_id)
    effective_order_id = request.order_id or (session or {}).get("order_id")
    previous_intent = (session or {}).get("last_intent")
    previous_unresolved = int((session or {}).get("unresolved_count", 0))
    follow_up_signal = any(normalized_message.startswith(prefix) for prefix in ("那", "还", "继续", "然后", "现在", "这个", "它")) or normalized_message in {"呢", "怎么办", "怎么处理"}
    # Explicit policy signals take precedence over a model classification so a
    # policy question cannot accidentally enter an order-dependent Tool path.
    policy_signal = any(word in normalized_message for word in ("规则", "政策", "时效", "多久能到", "几天送到", "到货", "发货后", "配送", "shippingpolicy", "returnpolicy"))
    return_signal = any(word in normalized_message for word in ("退货", "换货", "能退", "退吗", "iwanttoreturn", "returnthisorder"))
    logistics_signal = any(word in normalized_message for word in ("物流", "到哪里", "到哪了", "运输", "预计", "whereismyorder", "tracking"))
    payment_signal = any(word in message for word in ("银行卡", "收款人", "支付密码", "付款账户", "payment", "bank account"))
    complaint_signal = any(word in message for word in ("投诉", "退款争议", "一直不退"))
    unsupported_signal = any(word in normalized_message for word in ("海关税费", "永久退款", "任意商品"))
    explicit_intent = "payment_sensitive" if payment_signal else "complaint" if complaint_signal or unsupported_signal else "policy" if policy_signal else "logistics" if logistics_signal or "订单号" in normalized_message else "return" if return_signal else None
    if explicit_intent is None and follow_up_signal and previous_intent in {"logistics", "return", "policy"}:
        explicit_intent = previous_intent
    if explicit_intent is None and previous_intent in {"logistics", "return", "policy"} and len(normalized_message) <= 12:
        explicit_intent = previous_intent
    decision = {"intent": explicit_intent, "confidence": 0.99, "margin": 0.5} if explicit_intent else (deepseek.classify(message, trace_id) or _fallback_intent(message))
    intent = decision["intent"]
    if decision["confidence"] < INTENT_MIN_CONFIDENCE or decision["margin"] < INTENT_MIN_MARGIN or intent == "unknown":
        ticket = ticket_service.create(
            f"用户诉求：{message}", "low_confidence", "high", effective_order_id,
            f"assist-{trace_id}", trace_id, x_user_id,
        )
        ticket.data["handoff_reason"] = "意图置信度不足，无法安全确认"
        ticket.data["summary"] = {"user_request": message, "order_id": effective_order_id, "actions_taken": [], "handoff_reason": "意图置信度不足，无法安全确认"}
        ticket.message = "目前无法可靠确认您的问题类型，已转人工处理。"
        ticket.handoff = True
        record_tool("handoff_human", trace_id, ticket)
        record_conversation(trace_id, "unknown", ticket, request.session_id)
        conversations.save(request.session_id, user_id=x_user_id, order_id=effective_order_id, intent="unknown", resolved=False)
        return JSONResponse(status_code=200, content=ticket.model_dump())
    if intent in {"complaint", "payment_sensitive"}:
        category = "payment_sensitive" if intent == "payment_sensitive" else "complaint_or_dispute"
        handoff_reason = "支付敏感问题涉及支付账户或收款信息，必须由人工核验" if intent == "payment_sensitive" else "高风险投诉或退款争议默认转人工"
        ticket = ticket_service.create(
            f"用户诉求：{message}", category, "urgent", effective_order_id,
            f"assist-{trace_id}", trace_id, x_user_id,
        )
        ticket.data["handoff_reason"] = handoff_reason
        ticket.data["summary"] = {"user_request": message, "order_id": effective_order_id, "actions_taken": ["识别支付敏感意图" if intent == "payment_sensitive" else "识别高风险意图", "创建售后工单"], "handoff_reason": handoff_reason}
        ticket.message = "该问题涉及支付敏感信息，已停止自动处理并创建人工工单。" if intent == "payment_sensitive" else "该问题需要人工处理，已创建售后工单。"
        ticket.handoff = True
        record_tool("create_service_ticket", trace_id, ticket)
        record_conversation(trace_id, intent, ticket, request.session_id)
        conversations.save(request.session_id, user_id=x_user_id, order_id=effective_order_id, intent=intent, resolved=False)
        return JSONResponse(status_code=200, content=ticket.model_dump())
    if intent == "logistics":
        if not x_user_id or not effective_order_id:
            result = ToolResponse.failure(trace_id, "400_ORDER_REQUIRED", "请提供订单号并完成身份校验。")
        else:
            result = service.query(effective_order_id, x_user_id, trace_id)
        if result.success:
            logistics = result.data or {}
            latest = logistics.get("latest_event") or {}
            estimated_arrival = logistics.get("estimated_arrival")
            arrival_text = f"预计 {estimated_arrival} 到达。" if estimated_arrival else "暂未提供预计到达时间。"
            result.message = (
                f"订单 {logistics.get('order_id', request.order_id)} 当前状态为“{logistics.get('order_status', '未知')}”。"
                f"最新节点：{latest.get('description', '暂无')}（{latest.get('location', '未知地点')}）。"
                f"{arrival_text}"
            )
        record_tool("query_order_logistics", trace_id, result)
        record_conversation(trace_id, intent, result, request.session_id)
        conversations.save(request.session_id, user_id=x_user_id, order_id=effective_order_id, intent=intent, resolved=result.success)
        return JSONResponse(status_code=result.http_status, content=result.model_dump())
    if any(word in message for word in ("规则", "政策", "时效", "多久可以退", "多久能到", "配送")):
        intent = "policy"
    if intent == "return":
        return_reason = request.return_reason or _extract_return_reason(message) or (session or {}).get("return_reason")
        if not return_reason and previous_intent == "return" and any(word in message for word in ("尺码", "质量", "损坏", "不合适", "不喜欢")):
            return_reason = message.strip()
        if not x_user_id or not effective_order_id or not return_reason:
            result = ToolResponse.failure(trace_id, "400_RETURN_FIELDS_REQUIRED", "要判断退换货资格，请补充订单号和退货原因。示例：OD202608001，原因：尺码不合适。")
        else:
            result = return_service.check(effective_order_id, x_user_id, return_reason, trace_id)
        record_tool("check_return_eligibility", trace_id, result)
        record_conversation(trace_id, intent, result, request.session_id)
        conversations.save(request.session_id, user_id=x_user_id, order_id=effective_order_id, intent=intent, resolved=result.success and not result.handoff, return_reason=return_reason)
        if not result.success and previous_unresolved >= 1:
            ticket = ticket_service.create(f"用户连续两次未解决：{message}", "low_confidence", "high", effective_order_id, f"assist-{trace_id}", trace_id, x_user_id)
            ticket.data["handoff_reason"] = "同一会话连续两次未解决，转人工处理"
            ticket.message = "连续两次未能完成退货资格判断，已转人工处理。"
            ticket.handoff = True
            conversations.save(request.session_id, user_id=x_user_id, order_id=effective_order_id, intent=intent, resolved=False, unresolved_count=2)
            record_tool("handoff_human", trace_id, ticket)
            return JSONResponse(status_code=200, content=ticket.model_dump())
        return JSONResponse(status_code=result.http_status, content=result.model_dump())
    result = policy_service.search(message, "US", trace_id)
    if not result.success:
        result.message = "目前没有可验证的规则依据，建议转人工。"
        record_tool("search_policy", trace_id, result)
        record_conversation(trace_id, "policy", result, request.session_id)
        return JSONResponse(status_code=200, content=result.model_copy(update={"http_status": 200}).model_dump())
    if isinstance(result.data, dict) and result.data.get("answer"):
        result.message = result.data["answer"]
    else:
        result.message = "已根据生效规则并附引用回答。"
    record_tool("search_policy", trace_id, result)
    record_conversation(trace_id, "policy", result, request.session_id)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.get("/admin/metrics")
def admin_metrics(x_role: Optional[str] = Header(default=None)) -> JSONResponse:
    if x_role not in {"supervisor", "implementer"}:
        return JSONResponse(status_code=403, content={"success": False, "error_code": "403_ROLE_FORBIDDEN", "message": "需要主管或实施人员角色。"})
    return JSONResponse(status_code=200, content=events.metrics())


@app.get("/admin/events")
def admin_events(x_role: Optional[str] = Header(default=None)) -> JSONResponse:
    if x_role not in {"supervisor", "implementer"}:
        return JSONResponse(status_code=403, content={"success": False, "error_code": "403_ROLE_FORBIDDEN", "message": "需要主管或实施人员角色。"})
    return JSONResponse(status_code=200, content={"events": events.recent()})


def _fallback_intent(message: str) -> dict:
    if any(word in message for word in ("银行卡", "收款人", "支付密码", "付款账户", "payment", "bank account")):
        return {"intent": "payment_sensitive", "confidence": 0.99, "margin": 0.5}
    if any(word in message for word in ("投诉", "退款争议", "一直不退")):
        return {"intent": "complaint", "confidence": 0.99, "margin": 0.5}
    if any(word in message for word in ("物流", "到哪里", "到哪了", "运输")):
        return {"intent": "logistics", "confidence": 0.95, "margin": 0.3}
    if any(word in message for word in ("规则", "政策", "时效", "多久可以退")):
        return {"intent": "policy", "confidence": 0.9, "margin": 0.2}
    if any(word in message for word in ("退货", "换货", "能退", "退吗")):
        return {"intent": "return", "confidence": 0.95, "margin": 0.3}
    return {"intent": "unknown", "confidence": 0.4, "margin": 0.05}


def _extract_return_reason(message: str) -> Optional[str]:
    match = re.search(r"原因\s*[:：]\s*([^）)]+)", message)
    return match.group(1).strip() if match else None
