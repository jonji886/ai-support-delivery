"""Integration contract tests: Agent API <-> Customer Systems over real HTTP.

验证 P0 目标：
* Agent 侧服务不再直接读取 mock JSON，而是经 HTTP Client + Adapter + Mapper
  访问客户系统（OMS / Logistics）。
* Field Mapping：客户系统原始字段/枚举 -> 内部统一 schema。
* 契约错误映射：404 / 403 / 5xx / timeout。
"""
from __future__ import annotations

import os

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.support.customer_client import (
    CustomerSystemClient,
    OrderForbiddenError,
    OrderNotFoundError,
)
from apps.api.support.errors import ExternalTimeoutError, ExternalUnavailableError
from apps.api.support.mappers import CARRIER_CODES, FULFILLMENT_STATUS, map_oms_order

BASE_URL = os.getenv("MOCK_CUSTOMER_SYSTEMS_BASE_URL")
assert BASE_URL, "MOCK_CUSTOMER_SYSTEMS_BASE_URL must be set (see tests/conftest.py)"


@pytest.fixture(scope="module")
def client() -> CustomerSystemClient:
    return CustomerSystemClient(BASE_URL, timeout_ms=3000)


@pytest.fixture(scope="module")
def api() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Mock OMS contract: customer field naming is exposed as-is
# ---------------------------------------------------------------------------


def test_oms_contract_exposes_customer_field_names(client: CustomerSystemClient) -> None:
    payload = client.fetch_order("OD202608001", "user-demo-001")
    # 客户系统原始字段命名（与内部 schema 不同）
    assert payload["order_no"] == "OD202608001"
    assert payload["customer_ref"] == "user-demo-001"
    assert payload["fulfillment_status"] == "DELIVERED"
    assert payload["category_code"] == "STANDARD_GOODS"
    assert payload["signed_at"] == "2026-08-05T09:30:00Z"


def test_logistics_contract_exposes_customer_field_names(client: CustomerSystemClient) -> None:
    payload = client.fetch_tracking("OD202608001", "user-demo-001")
    assert payload["order_no"] == "OD202608001"
    assert payload["carrier_code"] == "DEMO_EXPRESS"
    assert payload["tracking_status"] == "SHIPPED"
    assert payload["has_exception"] is False


# ---------------------------------------------------------------------------
# Field Mapping: customer payload -> internal schema
# ---------------------------------------------------------------------------


def test_mapper_translates_customer_fields_to_internal_schema(
    client: CustomerSystemClient,
) -> None:
    oms = client.fetch_order("OD202608001", "user-demo-001")
    tracking = client.fetch_tracking("OD202608001", "user-demo-001")
    record = map_oms_order(oms, tracking)

    assert record["order_id"] == "OD202608001"
    assert record["anonymous_user_id"] == "user-demo-001"
    # DELIVERED -> 已签收
    assert record["order_status"] == FULFILLMENT_STATUS["DELIVERED"] == "已签收"
    # STANDARD_GOODS -> standard_goods
    assert record["category"] == "standard_goods"
    assert record["signed_at"] == "2026-08-05T09:30:00Z"
    # 物流映射：SHIPPED -> 运输中；DEMO_EXPRESS -> Demo Express
    assert record["logistics"]["order_status"] == FULFILLMENT_STATUS["SHIPPED"] == "运输中"
    assert record["logistics"]["carrier"] == CARRIER_CODES["DEMO_EXPRESS"] == "Demo Express"
    assert record["logistics"]["latest_event"]["location"] == "Los Angeles, US"
    assert record["logistics"]["exception"] is False
    assert record["logistics"]["estimated_arrival"] == "2026-08-15T18:00:00Z"


# ---------------------------------------------------------------------------
# Contract errors: 404 / 403 / 5xx / timeout
# ---------------------------------------------------------------------------


def test_unknown_order_maps_to_order_not_found(client: CustomerSystemClient) -> None:
    with pytest.raises(OrderNotFoundError):
        client.fetch_order("OD999999999", "user-demo-001")


def test_foreign_user_maps_to_forbidden(client: CustomerSystemClient) -> None:
    with pytest.raises(OrderForbiddenError):
        client.fetch_order("OD202608001", "user-demo-002")


def test_missing_user_header_is_rejected(client: CustomerSystemClient) -> None:
    with pytest.raises(ExternalUnavailableError):
        client._get("/oms/orders/OD202608001", "")


def test_upstream_5xx_maps_to_external_unavailable(client: CustomerSystemClient) -> None:
    with pytest.raises(ExternalUnavailableError):
        client.fetch_order("OD202608001", "user-demo-001", headers={"X-Fault-Inject": "500"})


def test_demo_fault_mode_is_forwarded_to_customer_system(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_CUSTOMER_FAULT", "500")
    faulted = CustomerSystemClient(BASE_URL, timeout_ms=3000)
    with pytest.raises(ExternalUnavailableError):
        faulted.fetch_order("OD202608001", "user-demo-001")


def test_upstream_timeout_maps_to_external_timeout() -> None:
    short = CustomerSystemClient(BASE_URL, timeout_ms=200)
    with pytest.raises(ExternalTimeoutError):
        short.fetch_order(
            "OD202608001", "user-demo-001", headers={"X-Fault-Inject": "timeout"}
        )


# ---------------------------------------------------------------------------
# End-to-end over HTTP: Agent API really reaches the customer systems
# ---------------------------------------------------------------------------


def test_api_query_flows_over_http_and_maps_fields(api: TestClient) -> None:
    response = api.post(
        "/tools/query-order-logistics",
        json={"order_id": "OD202608001"},
        headers={"X-User-Id": "user-demo-001"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    # 数据来自客户 OMS/Logistics（经 Mapper 转换后的内部字段）
    assert data["order_id"] == "OD202608001"
    assert data["order_status"] == "运输中"
    assert data["carrier"] == "Demo Express"
    assert data["latest_event"]["location"] == "Los Angeles, US"
    assert data["exception"] is False


def test_api_flow_reaches_customer_systems_over_http(api: TestClient) -> None:
    """通过 mock 服务的调用计数证明 Agent 真实发出了 HTTP 请求。"""
    stats = httpx.get(f"{BASE_URL}/admin/stats").json()
    before = stats["calls"].get("oms/orders", 0)

    api.post(
        "/tools/query-order-logistics",
        json={"order_id": "OD202608001"},
        headers={"X-User-Id": "user-demo-001"},
    )

    after = httpx.get(f"{BASE_URL}/admin/stats").json()["calls"].get("oms/orders", 0)
    assert after == before + 1


def test_api_404_maps_to_order_not_found(api: TestClient) -> None:
    response = api.post(
        "/tools/query-order-logistics",
        json={"order_id": "OD999999999"},
        headers={"X-User-Id": "user-demo-001"},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "404_ORDER_NOT_FOUND"


def test_api_403_maps_to_forbidden(api: TestClient) -> None:
    response = api.post(
        "/tools/query-order-logistics",
        json={"order_id": "OD202608001"},
        headers={"X-User-Id": "user-demo-002"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "403_ORDER_FORBIDDEN"
