from fastapi.testclient import TestClient
from uuid import uuid4

from apps.api.main import app, support_graph
from apps.api.agent.graph import REQUIRED_GRAPH_NODES

client = TestClient(app)


def test_assist_is_compiled_as_explicit_langgraph_workflow() -> None:
    graph = support_graph.get_graph()
    assert REQUIRED_GRAPH_NODES <= set(graph.nodes)
    assert {
        edge.target for edge in graph.edges if edge.source == "classify_intent"
    } == {
        "low_confidence_handoff",
        "risk_handoff",
        "query_logistics",
        "check_return_eligibility",
        "search_policy",
    }


def test_assist_logistics_uses_controlled_tool() -> None:
    response = client.post("/assist", json={"message": "订单到哪里了？", "order_id": "OD202608001"}, headers={"X-User-Id": "user-demo-001"})
    assert response.status_code == 200
    assert response.json()["data"]["order_status"] == "运输中"
    assert "最新节点" in response.json()["message"]
    assert "预计 2026-08-15T18:00:00Z 到达" in response.json()["message"]


def test_assist_core_colloquial_routes_do_not_require_model() -> None:
    logistics = client.post("/assist", json={"message": "帮我查下包裹", "order_id": "OD202608001"}, headers={"X-User-Id": "user-demo-001"})
    returned = client.post("/assist", json={"message": "尺码不合适，想退", "order_id": "OD202608001", "return_reason": "尺码不合适"}, headers={"X-User-Id": "user-demo-001"})
    complaint = client.post("/assist", json={"message": "客户一直没收到退款", "order_id": "OD202608001"})
    assert logistics.json()["data"]["order_status"] == "运输中"
    assert returned.json()["data"]["decision"] == "eligible"
    assert complaint.json()["data"]["category"] == "complaint_or_dispute"


def test_multi_intent_risk_signal_preempts_normal_tool() -> None:
    response = client.post(
        "/assist",
        json={"message": "包裹一直没到，我要投诉", "order_id": "OD202608001"},
        headers={"X-User-Id": "user-demo-001"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["category"] == "complaint_or_dispute"
    assert response.json()["handoff"] is True
    assert response.json()["data"]["summary"]["secondary_intents"] == ["logistics"]
    assert response.json()["data"]["summary"]["intent_catalog_version"] == "intent-catalog-v1"


def test_assist_complaint_handoffs_and_creates_ticket() -> None:
    response = client.post("/assist", json={"message": "一直不退款，我要投诉", "order_id": "OD202608001"})
    body = response.json()
    assert response.status_code == 200
    assert body["data"]["status"] == "待人工处理"
    assert body["data"]["handoff_reason"]
    assert body["data"]["summary"]["user_request"]


def test_assist_policy_has_citation() -> None:
    response = client.post("/assist", json={"message": "海外仓发货多久能到？"})
    assert response.status_code == 200
    assert response.json()["data"]["citations"]
    assert "5-10 个工作日" in response.json()["message"]


def test_assist_unknown_policy_is_controlled_handoff_message() -> None:
    response = client.post("/assist", json={"message": "帮我修改银行卡收款人"})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["handoff"] is True
    assert "人工" in response.json()["message"]


def test_payment_sensitive_has_independent_risk_route() -> None:
    response = client.post("/assist", json={"message": "帮我修改银行卡收款人"})
    body = response.json()
    assert response.status_code == 200
    assert body["data"]["category"] == "payment_sensitive"
    assert body["data"]["summary"]["actions_taken"][0] == "识别支付敏感意图"
    assert "支付敏感" in body["data"]["handoff_reason"]
    assert "自动处理" in body["message"]


def test_follow_up_inherits_order_and_intent_from_session() -> None:
    session_id = "conversation-logistics-01"
    first = client.post("/assist", json={"message": "订单到哪里了？", "order_id": "OD202608001", "session_id": session_id}, headers={"X-User-Id": "user-demo-001"})
    second = client.post("/assist", json={"message": "那预计什么时候到？", "session_id": session_id}, headers={"X-User-Id": "user-demo-001"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["order_id"] == "OD202608001"
    assert "预计 2026-08-15T18:00:00Z 到达" in second.json()["message"]


def test_follow_up_can_supply_missing_return_reason() -> None:
    session_id = "conversation-return-" + uuid4().hex
    first = client.post("/assist", json={"message": "我想退货", "order_id": "OD202608001", "session_id": session_id}, headers={"X-User-Id": "user-demo-001"})
    second = client.post("/assist", json={"message": "尺码不合适", "session_id": session_id}, headers={"X-User-Id": "user-demo-001"})
    assert first.status_code == 400
    assert second.status_code == 200
    assert second.json()["data"]["decision"] == "eligible"


def test_explicit_order_switch_does_not_reuse_old_return_reason(monkeypatch) -> None:
    from apps.api.main import conversations

    session_id = "conversation-order-switch-" + uuid4().hex
    conversations.save(
        session_id, user_id="user-demo-001", order_id="OD202608001", intent="return", resolved=False,
        return_reason="尺码不合适", slot_sources={"order_id": "user_explicit", "return_reason": "user_explicit"},
    )
    # Use a same-user synthetic order to isolate memory behavior from ownership.
    from apps.api.main import return_service
    original = return_service.orders.get("OD202608009")
    return_service.orders["OD202608009"] = {**return_service.orders["OD202608001"], "order_id": "OD202608009"}
    try:
        response = client.post(
            "/assist",
            json={"message": "这个订单能退吗", "order_id": "OD202608009", "session_id": session_id},
            headers={"X-User-Id": "user-demo-001"},
        )
    finally:
        if original is None:
            return_service.orders.pop("OD202608009", None)
        else:
            return_service.orders["OD202608009"] = original

    assert response.status_code == 400
    assert "退货原因" in response.json()["message"]


def test_two_unresolved_turns_trigger_handoff() -> None:
    session_id = "conversation-unresolved-" + uuid4().hex
    first = client.post("/assist", json={"message": "我想退货", "order_id": "OD202608001", "session_id": session_id}, headers={"X-User-Id": "user-demo-001"})
    second = client.post("/assist", json={"message": "还是想退", "session_id": session_id}, headers={"X-User-Id": "user-demo-001"})
    assert first.status_code == 400
    assert second.status_code == 200
    assert second.json()["handoff"] is True
    assert "连续两次" in second.json()["data"]["handoff_reason"]


def test_supervisor_can_read_metrics_but_consumer_cannot() -> None:
    denied = client.get("/admin/metrics")
    allowed = client.get("/admin/metrics", headers={"X-Role": "supervisor"})
    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert "tool_calls" in allowed.json()


def test_supervisor_metrics_include_business_explanations_and_trend_fields() -> None:
    response = client.get("/admin/metrics", headers={"X-Role": "supervisor"})
    body = response.json()
    assert response.status_code == 200
    assert "tool_success_rate" in body
    assert "handoff_rate" in body
    assert "citation_rate" in body
    assert "risk_count" in body
    assert "intent_distribution" in body
    assert "error_distribution" in body
    assert "trend" in body


def test_event_store_persists_events_across_instances(tmp_path) -> None:
    from apps.api.support.events import EventStore

    db_path = str(tmp_path / "events.db")
    first = EventStore(db_path)
    first.append(event_type="conversation", trace_id="persisted-trace", intent="logistics", success=True, handoff=False)
    second = EventStore(db_path)
    assert second.events_for_trace("persisted-trace")[0]["intent"] == "logistics"
    assert second.metrics()["conversation_count"] == 1


def test_low_confidence_is_handed_to_human(monkeypatch) -> None:
    from apps.api.main import deepseek
    monkeypatch.setattr(deepseek, "classify", lambda message, trace_id: {"intent": "unknown", "confidence": 0.2, "margin": 0.01})
    response = client.post("/assist", json={"message": "这个问题很复杂，请帮我处理"})
    assert response.status_code == 200
    assert response.json()["handoff"] is True
    assert response.json()["data"]["handoff_reason"]


def test_return_reason_can_be_extracted_from_user_message() -> None:
    response = client.post(
        "/assist",
        json={"message": "我想退货（原因：尺码不合适）", "order_id": "OD202608001"},
        headers={"X-User-Id": "user-demo-001"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["decision"] == "eligible"


def test_return_without_reason_is_a_clarification_not_a_generic_success() -> None:
    response = client.post(
        "/assist",
        json={"message": "我想退货", "order_id": "OD202608001"},
        headers={"X-User-Id": "user-demo-001"},
    )
    body = response.json()
    assert response.status_code == 400
    assert body["success"] is False
    assert body["message"] != "查询成功。"
    assert "退货原因" in body["message"]
    assert body["handoff"] is True


def test_policy_without_evidence_is_not_presented_as_success() -> None:
    response = client.post("/assist", json={"message": "帮我修改银行卡收款人"})
    body = response.json()
    assert body["handoff"] is True
    assert "无法" in body["message"] or "人工" in body["message"]
    assert body["data"]["status"] == "待人工处理"
