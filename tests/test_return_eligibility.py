from datetime import datetime, timezone

from fastapi.testclient import TestClient

from apps.api.main import app, return_service

client = TestClient(app)


def test_return_is_eligible_within_policy_window() -> None:
    response = client.post(
        "/tools/check-return-eligibility",
        json={"order_id": "OD202608001", "return_reason": "尺码不合适"},
        headers={"X-User-Id": "user-demo-001"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["eligible"] is True
    assert body["data"]["rule_version"] == "return-policy-v1"
    assert body["data"]["requires_human"] is False
    assert body["message"] == "符合退货条件，可提交退货申请。"


def test_return_requires_human_for_unreceived_order() -> None:
    response = client.post(
        "/tools/check-return-eligibility",
        json={"order_id": "OD202608002", "return_reason": "不想要了"},
        headers={"X-User-Id": "user-demo-002"},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "409_ORDER_STATUS_UNSUPPORTED"


def test_quality_complaint_is_not_auto_approved() -> None:
    response = client.post(
        "/tools/check-return-eligibility",
        json={"order_id": "OD202608001", "return_reason": "商品质量问题"},
        headers={"X-User-Id": "user-demo-001"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["data"]["decision"] == "human_review"
    assert body["data"]["requires_human"] is True


def test_return_order_ownership_is_enforced() -> None:
    response = client.post(
        "/tools/check-return-eligibility",
        json={"order_id": "OD202608001", "return_reason": "尺码不合适"},
        headers={"X-User-Id": "user-demo-002"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "403_ORDER_FORBIDDEN"
