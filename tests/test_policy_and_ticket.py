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
    queued = client.get("/agent/return-applications", headers={"X-Role": "agent"})
    assert submitted.status_code == 200
    assert queued.status_code == 200
    assert any(item["application_id"] == submitted.json()["data"]["application_id"] for item in queued.json()["applications"])


def test_return_application_can_be_approved_or_rejected_with_reason() -> None:
    approved = client.post("/tools/submit-return-application", json={"order_id": "OD202608001", "return_reason": "尺码不合适", "idempotency_key": "review-approved-01"}, headers={"X-User-Id": "user-demo-001"})
    application_id = approved.json()["data"]["application_id"]
    reviewed = client.post(f"/agent/return-applications/{application_id}/review", json={"decision": "approved"}, headers={"X-Role": "agent"})
    assert reviewed.status_code == 200
    assert reviewed.json()["data"]["status"] == "审核通过"
    duplicate = client.post(f"/agent/return-applications/{application_id}/review", json={"decision": "rejected", "reason": "重复测试"}, headers={"X-Role": "agent"})
    assert duplicate.status_code == 409

    rejected = client.post("/tools/submit-return-application", json={"order_id": "OD202608001", "return_reason": "尺码不合适", "idempotency_key": "review-rejected-01"}, headers={"X-User-Id": "user-demo-001"})
    rejected_id = rejected.json()["data"]["application_id"]
    missing_reason = client.post(f"/agent/return-applications/{rejected_id}/review", json={"decision": "rejected"}, headers={"X-Role": "agent"})
    assert missing_reason.status_code == 400
    finalized = client.post(f"/agent/return-applications/{rejected_id}/review", json={"decision": "rejected", "reason": "超过审核期限"}, headers={"X-Role": "agent"})
    assert finalized.status_code == 200
    assert finalized.json()["data"]["status"] == "审核不通过"


def test_return_application_review_requires_agent_role() -> None:
    submitted = client.post("/tools/submit-return-application", json={"order_id": "OD202608001", "return_reason": "尺码不合适", "idempotency_key": "review-auth-01"}, headers={"X-User-Id": "user-demo-001"})
    application_id = submitted.json()["data"]["application_id"]
    response = client.post(f"/agent/return-applications/{application_id}/review", json={"decision": "approved"}, headers={"X-Role": "consumer"})
    assert response.status_code == 403


def test_agent_can_process_ticket_and_cannot_repeat() -> None:
    created = client.post("/tools/create-service-ticket", json={"conversation_summary":"用户投诉退款延迟，需要人工处理。","category":"refund_dispute","priority":"high","order_id":"OD202608001","idempotency_key":"resolve-ticket-01"})
    ticket_id = created.json()["data"]["ticket_id"]
    resolved = client.post(f"/agent/tickets/{ticket_id}/resolve", json={"status":"已解决","reply":"已核实退款状态，并向用户说明处理结果。"}, headers={"X-Role":"agent"})
    assert resolved.status_code == 200
    assert resolved.json()["data"]["status"] == "已解决"
    duplicate = client.post(f"/agent/tickets/{ticket_id}/resolve", json={"status":"已升级主管","reply":"重复处理"}, headers={"X-Role":"agent"})
    assert duplicate.status_code == 409


def test_consumer_can_see_agent_ticket_reply() -> None:
    created = client.post("/tools/create-service-ticket", json={"conversation_summary":"需要人工回复","category":"complaint","priority":"high","order_id":"OD202608001","idempotency_key":"consumer-ticket-01"}, headers={"X-User-Id":"user-demo-001"})
    ticket_id = created.json()["data"]["ticket_id"]
    client.post(f"/agent/tickets/{ticket_id}/resolve", json={"status":"已解决","reply":"人工客服已核实并回复。"}, headers={"X-Role":"agent"})
    latest = client.get(f"/tools/tickets/{ticket_id}", headers={"X-User-Id":"user-demo-001"})
    assert latest.status_code == 200
    assert latest.json()["data"]["agent_reply"] == "人工客服已核实并回复。"


def test_consumer_sees_latest_status_after_manual_review() -> None:
    submitted = client.post("/tools/submit-return-application", json={"order_id": "OD202608001", "return_reason": "尺码不合适", "idempotency_key": "consumer-status-01"}, headers={"X-User-Id": "user-demo-001"})
    application_id = submitted.json()["data"]["application_id"]
    client.post(f"/agent/return-applications/{application_id}/review", json={"decision": "approved"}, headers={"X-Role": "agent"})
    latest = client.get(f"/tools/return-applications/{application_id}", headers={"X-User-Id": "user-demo-001"})
    assert latest.status_code == 200
    assert latest.json()["data"]["status"] == "审核通过"


def test_success_response_requires_explicit_business_message() -> None:
    import inspect
    from apps.api.support.responses import ToolResponse
    parameter = inspect.signature(ToolResponse.success_result).parameters["message"]
    assert parameter.default is inspect.Parameter.empty
