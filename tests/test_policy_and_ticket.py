from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_policy_returns_citation() -> None:
    response = client.post("/tools/search-policy", json={"question": "海外仓发货多久能到？", "region": "US"})
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["data"]["citations"][0]["version"] == "shipping-policy-v1"
    assert body["data"]["citations"][0]["source"]


def test_policy_without_evidence_is_rejected() -> None:
    response = client.post("/tools/search-policy", json={"question": "如何修改收货人银行卡？", "region": "US"})
    assert response.status_code == 404
    assert response.json()["error_code"] == "404_POLICY_NOT_FOUND"


def test_ticket_creation_is_idempotent() -> None:
    payload = {
        "conversation_summary": "用户明确投诉退款延迟，需要人工处理。",
        "category": "refund_dispute",
        "priority": "high",
        "order_id": "OD202608001",
        "idempotency_key": "conversation-001-event-01",
    }
    first = client.post("/tools/create-service-ticket", json=payload).json()
    second = client.post("/tools/create-service-ticket", json=payload).json()
    assert first["data"]["ticket_id"] == second["data"]["ticket_id"]
    assert second["message"] == "已返回同一幂等请求创建的工单。"


def test_handoff_tool_returns_handoff_marker() -> None:
    response = client.post("/tools/handoff-human", json={
        "conversation_summary": "用户连续两次未解决物流问题。",
        "reason": "连续追问未解决",
        "idempotency_key": "handoff-session-01",
    })
    assert response.status_code == 200
    assert response.json()["handoff"] is True
    assert response.json()["data"]["handoff_reason"] == "连续追问未解决"


def test_each_successful_tool_has_business_specific_message() -> None:
    logistics = client.post(
        "/tools/query-order-logistics", json={"order_id": "OD202608001"},
        headers={"X-User-Id": "user-demo-001"},
    ).json()
    policy = client.post("/tools/search-policy", json={"question": "海外仓发货多久能到？"}).json()
    ticket = client.post("/tools/create-service-ticket", json={
        "conversation_summary": "需要客服处理退款争议。", "category": "refund_dispute",
        "priority": "high", "idempotency_key": "message-contract-01",
    }).json()
    assert logistics["message"] != "查询成功。"
    assert "规则" in policy["message"] or "生效" in policy["message"]
    assert "工单" in ticket["message"]


def test_return_application_requires_identity_and_is_idempotent() -> None:
    payload = {"order_id": "OD202608001", "return_reason": "尺码不合适", "idempotency_key": "return-application-01"}
    denied = client.post("/tools/submit-return-application", json=payload)
    first = client.post("/tools/submit-return-application", json=payload, headers={"X-User-Id": "user-demo-001"})
    second = client.post("/tools/submit-return-application", json=payload, headers={"X-User-Id": "user-demo-001"})
    assert denied.status_code == 400
    assert first.json()["data"]["status"] == "待审核"
    assert first.json()["data"]["application_id"] == second.json()["data"]["application_id"]
    assert "退款已完成" in first.json()["data"]["notice"]


def test_return_application_appears_in_manual_review_queue() -> None:
    payload = {"order_id": "OD202608001", "return_reason": "尺码不合适", "idempotency_key": "return-application-queue-01"}
    submitted = client.post("/tools/submit-return-application", json=payload, headers={"X-User-Id": "user-demo-001"})
    queued = client.get("/agent/return-applications", headers={"X-Role": "agent", "X-User-Id": "agent-demo-001"})
    assert submitted.status_code == 200
    assert queued.status_code == 200
    assert any(item["application_id"] == submitted.json()["data"]["application_id"] for item in queued.json()["applications"])


def test_return_application_can_be_approved_or_rejected_with_reason() -> None:
    approved = client.post("/tools/submit-return-application", json={"order_id": "OD202608001", "return_reason": "尺码不合适", "idempotency_key": "review-approved-01"}, headers={"X-User-Id": "user-demo-001"})
    application_id = approved.json()["data"]["application_id"]
    reviewed = client.post(f"/agent/return-applications/{application_id}/review", json={"decision": "approved"}, headers={"X-Role": "agent", "X-User-Id": "agent-demo-001"})
    assert reviewed.status_code == 200
    assert reviewed.json()["data"]["status"] == "审核通过"
    duplicate = client.post(f"/agent/return-applications/{application_id}/review", json={"decision": "rejected", "reason": "重复测试"}, headers={"X-Role": "agent", "X-User-Id": "agent-demo-001"})
    assert duplicate.status_code == 409

    rejected = client.post("/tools/submit-return-application", json={"order_id": "OD202608001", "return_reason": "尺码不合适", "idempotency_key": "review-rejected-01"}, headers={"X-User-Id": "user-demo-001"})
    rejected_id = rejected.json()["data"]["application_id"]
    missing_reason = client.post(f"/agent/return-applications/{rejected_id}/review", json={"decision": "rejected"}, headers={"X-Role": "agent", "X-User-Id": "agent-demo-001"})
    assert missing_reason.status_code == 400
    finalized = client.post(f"/agent/return-applications/{rejected_id}/review", json={"decision": "rejected", "reason": "超过审核期限"}, headers={"X-Role": "agent", "X-User-Id": "agent-demo-001"})
    assert finalized.status_code == 200
    assert finalized.json()["data"]["status"] == "审核不通过"


def test_return_application_review_requires_agent_role() -> None:
    submitted = client.post("/tools/submit-return-application", json={"order_id": "OD202608001", "return_reason": "尺码不合适", "idempotency_key": "review-auth-01"}, headers={"X-User-Id": "user-demo-001"})
    application_id = submitted.json()["data"]["application_id"]
    response = client.post(f"/agent/return-applications/{application_id}/review", json={"decision": "approved"}, headers={"X-Role": "consumer"})
    assert response.status_code == 403


def test_staff_queue_rejects_consumer_identity_even_with_staff_role() -> None:
    response = client.get("/agent/tickets", headers={"X-Role": "agent", "X-User-Id": "user-demo-001"})
    assert response.status_code == 403
    assert response.json()["error_code"] == "403_IDENTITY_FORBIDDEN"


def test_payment_account_wording_uses_payment_sensitive_route() -> None:
    response = client.post("/assist", json={"message": "我要更换支付账户"}, headers={"X-User-Id": "user-demo-001"})
    assert response.status_code == 200
    assert response.json()["data"]["category"] == "payment_sensitive"


def test_ticket_and_return_application_survive_new_service_instances(tmp_path) -> None:
    from apps.api.services.ticket import TicketService
    from apps.api.services.return_application import ReturnApplicationService
    from apps.api.services.order_logistics import OrderLogisticsService

    db_path = str(tmp_path / "support.db")
    tickets = TicketService(db_path=db_path)
    created = tickets.create("需要人工处理", "complaint", "high", "OD202608001", "restart-ticket-01", "trace-1", "user-demo-001")
    applications = ReturnApplicationService(OrderLogisticsService.from_default_data().records, db_path=db_path)
    submitted = applications.submit("OD202608001", "user-demo-001", "尺码不合适", "restart-return-01", "trace-2")

    assert TicketService(db_path=db_path).get_for_user(created.data["ticket_id"], "user-demo-001", "trace-3").success
    assert ReturnApplicationService(OrderLogisticsService.from_default_data().records, db_path=db_path).get_for_user(submitted.data["application_id"], "user-demo-001", "trace-4").success


def test_idempotency_key_cannot_be_reused_by_another_user() -> None:
    payload = {"conversation_summary": "需要人工处理", "category": "complaint", "priority": "high", "idempotency_key": "cross-user-key-01"}
    first = client.post("/tools/create-service-ticket", json=payload, headers={"X-User-Id": "user-demo-001"})
    second = client.post("/tools/create-service-ticket", json=payload, headers={"X-User-Id": "user-demo-002"})
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error_code"] == "409_IDEMPOTENCY_KEY_CONFLICT"


def test_staff_queues_support_pagination_and_filters() -> None:
    ticket_response = client.get(
        "/agent/tickets?page=1&page_size=1&keyword=TK&status=%E5%BE%85%E4%BA%BA%E5%B7%A5%E5%A4%84%E7%90%86",
        headers={"X-Role": "agent", "X-User-Id": "agent-demo-001"},
    )
    application_response = client.get(
        "/agent/return-applications?page=1&page_size=1&keyword=OD202608001&status=%E5%BE%85%E5%AE%A1%E6%A0%B8",
        headers={"X-Role": "agent", "X-User-Id": "agent-demo-001"},
    )
    assert ticket_response.status_code == 200
    assert application_response.status_code == 200
    assert ticket_response.json()["pagination"]["page_size"] == 1
    assert application_response.json()["pagination"]["page_size"] == 1
    assert len(ticket_response.json()["tickets"]) <= 1
    assert len(application_response.json()["applications"]) <= 1


def test_agent_can_process_ticket_and_cannot_repeat() -> None:
    created = client.post("/tools/create-service-ticket", json={"conversation_summary":"用户投诉退款延迟，需要人工处理。","category":"refund_dispute","priority":"high","order_id":"OD202608001","idempotency_key":"resolve-ticket-01"}, headers={"X-User-Id":"user-demo-001"})
    ticket_id = created.json()["data"]["ticket_id"]
    resolved = client.post(f"/agent/tickets/{ticket_id}/resolve", json={"status":"已解决","reply":"已核实退款状态，并向用户说明处理结果。"}, headers={"X-Role":"agent", "X-User-Id":"agent-demo-001"})
    assert resolved.status_code == 200
    assert resolved.json()["data"]["status"] == "已解决"
    duplicate = client.post(f"/agent/tickets/{ticket_id}/resolve", json={"status":"已升级主管","reply":"重复处理"}, headers={"X-Role":"agent", "X-User-Id":"agent-demo-001"})
    assert duplicate.status_code == 409


def test_consumer_can_see_agent_ticket_reply() -> None:
    created = client.post("/tools/create-service-ticket", json={"conversation_summary":"需要人工回复","category":"complaint","priority":"high","order_id":"OD202608001","idempotency_key":"consumer-ticket-01"}, headers={"X-User-Id":"user-demo-001"})
    ticket_id = created.json()["data"]["ticket_id"]
    client.post(f"/agent/tickets/{ticket_id}/resolve", json={"status":"已解决","reply":"人工客服已核实并回复。"}, headers={"X-Role":"agent", "X-User-Id":"agent-demo-001"})
    latest = client.get(f"/tools/tickets/{ticket_id}", headers={"X-User-Id":"user-demo-001"})
    assert latest.status_code == 200
    assert latest.json()["data"]["agent_reply"] == "人工客服已核实并回复。"


def test_consumer_sees_latest_status_after_manual_review() -> None:
    submitted = client.post("/tools/submit-return-application", json={"order_id": "OD202608001", "return_reason": "尺码不合适", "idempotency_key": "consumer-status-01"}, headers={"X-User-Id": "user-demo-001"})
    application_id = submitted.json()["data"]["application_id"]
    client.post(f"/agent/return-applications/{application_id}/review", json={"decision": "approved"}, headers={"X-Role": "agent", "X-User-Id": "agent-demo-001"})
    latest = client.get(f"/tools/return-applications/{application_id}", headers={"X-User-Id": "user-demo-001"})
    assert latest.status_code == 200
    assert latest.json()["data"]["status"] == "审核通过"


def test_success_response_requires_explicit_business_message() -> None:
    import inspect
    from apps.api.support.responses import ToolResponse
    parameter = inspect.signature(ToolResponse.success_result).parameters["message"]
    assert parameter.default is inspect.Parameter.empty
