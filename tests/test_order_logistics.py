from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_query_returns_only_verified_order_data() -> None:
    response = client.post(
        "/tools/query-order-logistics",
        json={"order_id": "OD202608001"},
        headers={"X-User-Id": "user-demo-001"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["order_status"] == "运输中"
    assert body["trace_id"]


def test_order_ownership_is_enforced() -> None:
    response = client.post(
        "/tools/query-order-logistics",
        json={"order_id": "OD202608001"},
        headers={"X-User-Id": "user-demo-002"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "403_ORDER_FORBIDDEN"
    assert response.json()["success"] is False


def test_missing_order_does_not_make_up_logistics_status() -> None:
    response = client.post(
        "/tools/query-order-logistics",
        json={"order_id": "OD202609999"},
        headers={"X-User-Id": "user-demo-001"},
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "404_ORDER_NOT_FOUND"
    assert response.json()["data"] is None


def test_invalid_order_id_is_rejected() -> None:
    response = client.post(
        "/tools/query-order-logistics",
        json={"order_id": "not-an-order"},
        headers={"X-User-Id": "user-demo-001"},
    )

    assert response.status_code == 422


def test_identity_is_required() -> None:
    response = client.post("/tools/query-order-logistics", json={"order_id": "OD202608001"})

    assert response.status_code == 400
    assert response.json()["error_code"] == "401_MISSING_USER"
