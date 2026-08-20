"""MVP API entrypoint for the controlled order/logistics tool."""

from fastapi import FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import os
import uuid

from apps.api.schemas import AssistRequest, CheckReturnEligibilityRequest, CreateServiceTicketRequest, HandoffHumanRequest, QueryOrderLogisticsRequest, SearchPolicyRequest, SubmitReturnApplicationRequest, ReviewReturnApplicationRequest, ResolveTicketRequest
from apps.api.services.order_logistics import OrderLogisticsService
from apps.api.services.policy_search import PolicySearchService
from apps.api.services.return_eligibility import ReturnEligibilityService
from apps.api.services.ticket import TicketService
from apps.api.services.return_application import ReturnApplicationService
from apps.api.services.deepseek import DeepSeekClient
from apps.api.services.intent_catalog import IntentCatalog
from apps.api.skills.contracts import SkillExecutionContext
from apps.api.skills.executor import SkillExecutor
from apps.api.skills.handlers import SkillHandlerDependencies, SupportSkillHandlers
from apps.api.skills.registry import SkillRegistry
from apps.api.support.customer_client import CustomerSystemClient
from apps.api.support.responses import ToolResponse, new_trace_id
from apps.api.support.events import EventStore
from apps.api.support.conversations import ConversationStore
from apps.api.support.observability import TraceStore
from apps.api.agent.graph import SupportGraphDependencies, build_support_graph
from apps.api.memory import MemoryManager

app = FastAPI(title="AI Support Delivery API", version="0.1.0")
_cors_origins = ["http://localhost:8080", "http://127.0.0.1:8080", "http://localhost:5173", "http://127.0.0.1:5173"]
_web_public = os.environ.get("WEB_PUBLIC_ORIGIN")
if _web_public:
    _cors_origins.append(_web_public)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-User-Id", "X-Role", "X-Trace-Id"],
    expose_headers=["X-Trace-Id"],
)
# 客户系统集成边界：Agent 侧服务通过 HTTP Client 访问 Mock Customer Systems
# （OMS + Logistics），不再直接读取 mock JSON。集成测试/本地开发通过
# MOCK_CUSTOMER_SYSTEMS_BASE_URL 指向 mock 服务地址。
_customer_base_url = os.getenv("MOCK_CUSTOMER_SYSTEMS_BASE_URL", "http://127.0.0.1:8001")
_customer_client = CustomerSystemClient(base_url=_customer_base_url)
service = OrderLogisticsService.from_http(_customer_client)
return_service = ReturnEligibilityService.from_http(_customer_client)
policy_service = PolicySearchService.from_default_data()
ticket_service = TicketService()
return_application_service = ReturnApplicationService(client=_customer_client)
deepseek = DeepSeekClient()
events = EventStore(os.getenv("EVENTS_DB_PATH", "runtime/events.db"))
traces = TraceStore()
conversations = ConversationStore()
memory_manager = MemoryManager(conversation_store=conversations)
intent_catalog = IntentCatalog.from_default_data()
skill_registry = SkillRegistry.from_default_manifests()
skill_executor = SkillExecutor(skill_registry, traces)
STAFF_IDENTITIES = {
    "agent": "agent-demo-001",
    "supervisor": "supervisor-demo-001",
    "implementer": "implementer-demo-001",
}


@app.middleware("http")
async def observe_request(request: Request, call_next):
    # This service creates the trace root. Do not trust a caller-provided ID:
    # reusing one could overwrite an earlier local trace.
    trace_id = uuid.uuid4().hex
    token, started = traces.begin_trace(
        trace_id,
        name=f"{request.method} <pending>",
        route="<pending>",
        method=request.method,
        attributes={"service.name": "ai-support-api", "deployment.environment": os.getenv("APP_ENV", "demo"), "http.request.method": request.method},
    )
    try:
        response = await call_next(request)
        route_template = getattr(request.scope.get("route"), "path", "<unmatched>")
        traces.end_trace(trace_id, started, status_code=response.status_code, route=route_template)
    except Exception as exc:
        route_template = getattr(request.scope.get("route"), "path", "<unmatched>")
        traces.end_trace(trace_id, started, status_code=500, route=route_template, error=exc, error_code="500_INTERNAL_ERROR")
        response = JSONResponse(
            status_code=500,
            content={"success": False, "data": None, "error_code": "500_INTERNAL_ERROR", "message": "系统处理失败，请使用 trace_id 联系技术支持。", "trace_id": trace_id, "http_status": 500, "handoff": True},
        )
    finally:
        traces.reset_trace(token)
    response.headers["X-Trace-Id"] = trace_id
    return response


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


skill_handlers = SupportSkillHandlers(
    SkillHandlerDependencies(
        logistics=service,
        returns=return_service,
        return_applications=return_application_service,
        policies=policy_service,
        tickets=ticket_service,
        record_tool=record_tool,
        record_conversation=record_conversation,
    )
)


def staff_identity_allowed(role: Optional[str], user_id: Optional[str]) -> bool:
    return bool(role and user_id and user_id == STAFF_IDENTITIES.get(role))


support_graph = build_support_graph(
    SupportGraphDependencies(
        logistics=service,
        returns=return_service,
        policies=policy_service,
        tickets=ticket_service,
        model=deepseek,
        conversations=conversations,
        record_tool=record_tool,
        record_conversation=record_conversation,
        observability=traces,
        intents=intent_catalog,
        skills=skill_registry,
        skill_executor=skill_executor,
        skill_handlers=skill_handlers,
    )
)


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
def create_service_ticket(request: CreateServiceTicketRequest, x_user_id: Optional[str] = Header(default=None)) -> JSONResponse:
    trace_id = new_trace_id()
    result = ticket_service.create(
        request.conversation_summary, request.category, request.priority,
        request.order_id, request.idempotency_key, trace_id, x_user_id,
    )
    events.append(event_type="tool", tool_name="create_service_ticket", trace_id=trace_id, success=result.success, error_code=result.error_code)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.post("/tools/handoff-human")
def handoff_human(request: HandoffHumanRequest, x_user_id: Optional[str] = Header(default=None)) -> JSONResponse:
    trace_id = new_trace_id()
    result = ticket_service.create(
        request.conversation_summary, request.category, request.priority,
        request.order_id, request.idempotency_key, trace_id, x_user_id,
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
    outcome = skill_executor.execute(
        "return_resolution",
        SkillExecutionContext(
            trace_id=trace_id,
            intent="return",
            phase="confirm_submit",
            confirmed=True,
            payload={
                "order_id": request.order_id,
                "user_id": x_user_id,
                "return_reason": request.return_reason,
                "idempotency_key": request.idempotency_key,
            },
        ),
        skill_handlers.return_resolution,
    )
    result = outcome.result
    if not x_user_id and result.error_code == "400_RETURN_FIELDS_REQUIRED":
        result = ToolResponse.failure(trace_id, "401_MISSING_USER", "缺少用户身份，无法提交退货申请。")
    record_tool(outcome.tool_name, trace_id, result)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.get("/agent/return-applications")
def agent_return_applications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=8, ge=1, le=100),
    keyword: Optional[str] = Query(default=None, max_length=100),
    status: str = Query(default="待审核", max_length=20),
    x_role: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Return the manual review queue for customer-service roles."""
    if x_role not in {"agent", "supervisor", "implementer"}:
        return JSONResponse(status_code=403, content={"success": False, "error_code": "403_ROLE_FORBIDDEN", "message": "需要人工客服、主管或实施人员角色。"})
    if not x_user_id:
        return JSONResponse(status_code=401, content={"success": False, "error_code": "401_MISSING_USER", "message": "缺少登录身份，无法查看人工审核队列。"})
    if not staff_identity_allowed(x_role, x_user_id):
        return JSONResponse(status_code=403, content={"success": False, "error_code": "403_IDENTITY_FORBIDDEN", "message": "当前身份无权查看人工审核队列。"})
    result = return_application_service.pending(page=page, page_size=page_size, keyword=keyword, status=status)
    return JSONResponse(status_code=200, content={"applications": result["items"], "pagination": {key: result[key] for key in ("page", "page_size", "total")}})


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
def review_return_application(application_id: str, request: ReviewReturnApplicationRequest, x_role: Optional[str] = Header(default=None), x_user_id: Optional[str] = Header(default=None)) -> JSONResponse:
    trace_id = new_trace_id()
    if x_role not in {"agent", "supervisor"}:
        result = ToolResponse.failure(trace_id, "403_ROLE_FORBIDDEN", "只有人工客服或主管可以审核退货申请。", 403)
    elif not x_user_id:
        result = ToolResponse.failure(trace_id, "401_MISSING_USER", "缺少登录身份，无法审核退货申请。", 401)
    elif not staff_identity_allowed(x_role, x_user_id):
        result = ToolResponse.failure(trace_id, "403_IDENTITY_FORBIDDEN", "当前身份无权审核退货申请。", 403)
    else:
        result = return_application_service.review(application_id, x_role, request.decision, request.reason, trace_id)
    record_tool("review_return_application", trace_id, result)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.get("/agent/tickets")
def agent_tickets(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=8, ge=1, le=100),
    keyword: Optional[str] = Query(default=None, max_length=100),
    status: Optional[str] = Query(default=None, max_length=20),
    category: Optional[str] = Query(default=None, max_length=50),
    x_role: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
) -> JSONResponse:
    if x_role not in {"agent", "supervisor", "implementer"}:
        return JSONResponse(status_code=403, content={"success": False, "error_code": "403_ROLE_FORBIDDEN", "message": "需要客服、主管或实施人员角色。"})
    if not x_user_id:
        return JSONResponse(status_code=401, content={"success": False, "error_code": "401_MISSING_USER", "message": "缺少登录身份，无法查看人工工单。"})
    if not staff_identity_allowed(x_role, x_user_id):
        return JSONResponse(status_code=403, content={"success": False, "error_code": "403_IDENTITY_FORBIDDEN", "message": "当前身份无权查看人工工单。"})
    result = ticket_service.list_tickets(page=page, page_size=page_size, keyword=keyword, status=status, category=category)
    return JSONResponse(status_code=200, content={"tickets": result["items"], "pagination": {key: result[key] for key in ("page", "page_size", "total")}})


@app.post("/agent/tickets/{ticket_id}/resolve")
def resolve_ticket(ticket_id: str, request: ResolveTicketRequest, x_role: Optional[str] = Header(default=None), x_user_id: Optional[str] = Header(default=None)) -> JSONResponse:
    trace_id = new_trace_id()
    if x_role not in {"agent", "supervisor"}:
        result = ToolResponse.failure(trace_id, "403_ROLE_FORBIDDEN", "只有人工客服或主管可以处理工单。", 403)
    elif not x_user_id:
        result = ToolResponse.failure(trace_id, "401_MISSING_USER", "缺少登录身份，无法处理工单。", 401)
    elif not staff_identity_allowed(x_role, x_user_id):
        result = ToolResponse.failure(trace_id, "403_IDENTITY_FORBIDDEN", "当前身份无权处理工单。", 403)
    else:
        result = ticket_service.resolve(ticket_id, request.status, request.reply, trace_id)
    record_tool("resolve_service_ticket", trace_id, result)
    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.post("/assist")
def assist(request: AssistRequest, x_user_id: Optional[str] = Header(default=None)) -> JSONResponse:
    """Run the controlled LangGraph workflow; tools remain the source of truth."""
    trace_id = new_trace_id()

    # Memory: record conversation message before agent processing
    if x_user_id and request.session_id:
        memory_manager.record_conversation_message(
            user_id=x_user_id,
            session_id=request.session_id,
            role="user",
            content=request.message,
        )
        # Extract and persist long-term memory candidates from user message
        memory_manager.process_user_message(
            request.message,
            user_id=x_user_id,
            session_id=request.session_id,
        )

    final_state = support_graph.invoke({"request": request, "user_id": x_user_id, "trace_id": trace_id})
    result = final_state["result"]

    # Memory: record AI response and inject memory context into response
    if x_user_id and request.session_id and result.success and result.data:
        answer = result.data.get("answer", "") if isinstance(result.data, dict) else ""
        if answer:
            memory_manager.record_conversation_message(
                user_id=x_user_id,
                session_id=request.session_id,
                role="assistant",
                content=answer,
            )
        # Retrieve memory context for Inspector visibility
        memory_context = memory_manager.retrieve_context(
            user_id=x_user_id,
            session_id=request.session_id,
            current_intent=final_state.get("intent"),
            current_order_id=final_state.get("effective_order_id"),
        )
        if memory_context:
            result.data["memory_context"] = memory_context

    return JSONResponse(status_code=result.http_status, content=result.model_dump())


@app.get("/admin/memory/{user_id}")
def admin_memory_inspector(
    user_id: str,
    memory_type: Optional[str] = Query(default=None),
    x_role: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Memory Inspector — view all memory for a user."""
    if x_role not in {"supervisor", "implementer"}:
        return JSONResponse(status_code=403, content={"success": False, "error_code": "403_ROLE_FORBIDDEN", "message": "需要主管或实施人员角色。"})
    records = memory_manager.list_memory(user_id, memory_type=memory_type)
    return JSONResponse(status_code=200, content={
        "user_id": user_id,
        "memories": [r.to_dict() for r in records],
        "total": len(records),
    })


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


@app.get("/admin/traces/{trace_id}")
def admin_trace(trace_id: str, x_role: Optional[str] = Header(default=None)) -> JSONResponse:
    if x_role not in {"supervisor", "implementer"}:
        return JSONResponse(status_code=403, content={"success": False, "error_code": "403_ROLE_FORBIDDEN", "message": "需要主管或实施人员角色。"})
    result = traces.get_trace(trace_id)
    if result is None:
        return JSONResponse(status_code=404, content={"success": False, "error_code": "404_TRACE_NOT_FOUND", "message": "未找到该运行链路。"})
    return JSONResponse(status_code=200, content=result)


@app.get("/admin/observability/summary")
def admin_observability_summary(
    window_minutes: int = Query(default=60, ge=1, le=10080),
    x_role: Optional[str] = Header(default=None),
) -> JSONResponse:
    if x_role not in {"supervisor", "implementer"}:
        return JSONResponse(status_code=403, content={"success": False, "error_code": "403_ROLE_FORBIDDEN", "message": "需要主管或实施人员角色。"})
    return JSONResponse(status_code=200, content=traces.summary(window_minutes))
