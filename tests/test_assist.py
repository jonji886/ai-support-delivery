from fastapi.testclient import TestClient
from uuid import uuid4

from apps.api.main import app

client = TestClient(app)


def test_assist_logistics_uses_controlled_tool() -> None:
    response = client.post("/assist", json={"message": "订单到哪里了？", "order_id": "OD202608001"}, headers={"X-User-Id": "user-demo-001"})
    assert response.status_code == 200
    assert response.json()["data"]["order_status"] == "运输中"
    assert "最新节点" in response.json()["message"]
    assert "预计 2026-08-15T18:00:00Z 到达" in response.json()["message"]


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
