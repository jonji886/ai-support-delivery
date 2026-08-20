"""Field mapping between customer system payloads and the internal schema.

客户系统（OMS / Logistics）使用自己的字段命名和枚举，Agent 侧内部 schema 使用
统一的中文状态与内部字段名。本模块是集成边界的"翻译层"：

========================  ==============================================
客户系统字段               内部 schema 字段
========================  ==============================================
order_no                  order_id
customer_ref              anonymous_user_id
fulfillment_status        枚举映射 -> order_status（中文）
category_code             枚举映射 -> category
signed_at                 signed_at
carrier_code              枚举映射 -> logistics.carrier
tracking_status           枚举映射 -> logistics.order_status
tracking_events[last]     logistics.latest_event
has_exception             logistics.exception
eta                       logistics.estimated_arrival
========================  ==============================================

所有映射均有测试覆盖（``tests/test_customer_integration_contract.py``）。
"""
from __future__ import annotations

from typing import Optional

#: Customer OMS fulfillment status -> internal order status.
FULFILLMENT_STATUS: dict[str, str] = {
    "PENDING": "待发货",
    "SHIPPED": "运输中",
    "DELIVERED": "已签收",
    "EXCEPTION": "物流异常",
    "COMPLETED": "已完成",
}

#: Customer OMS category code -> internal category id.
CATEGORY_CODES: dict[str, str] = {
    "STANDARD_GOODS": "standard_goods",
    "DIGITAL_GOODS": "digital_goods",
    "FRAGILE_GOODS": "fragile_goods",
    "LARGE_APPLIANCE": "large_appliance",
}

#: Customer logistics carrier code -> internal carrier display name.
CARRIER_CODES: dict[str, str] = {
    "DEMO_EXPRESS": "Demo Express",
    "DEMO_POST": "Demo Post",
}


def map_oms_order(oms: dict, tracking: Optional[dict] = None) -> dict:
    """Map a customer OMS order (and optional logistics tracking) to the
    internal order record schema.

    The returned dict matches the shape of ``data/mock/orders.json`` records,
    so services can treat HTTP-fetched data and in-memory data identically.
    """
    tracking = tracking or {}
    events = tracking.get("tracking_events") or []
    latest = events[-1] if events else None
    return {
        "order_id": oms["order_no"],
        "anonymous_user_id": oms["customer_ref"],
        "order_status": _map_enum(FULFILLMENT_STATUS, oms.get("fulfillment_status")),
        "category": _map_enum(CATEGORY_CODES, oms.get("category_code")),
        "signed_at": oms.get("signed_at"),
        "logistics": {
            "order_id": oms["order_no"],
            "order_status": _map_enum(FULFILLMENT_STATUS, tracking.get("tracking_status")),
            "carrier": _map_enum(CARRIER_CODES, tracking.get("carrier_code")),
            "latest_event": {
                "occurred_at": latest["event_time"],
                "location": latest["location"],
                "description": latest["description"],
            }
            if latest
            else None,
            "exception": bool(tracking.get("has_exception", False)),
            "estimated_arrival": tracking.get("eta"),
        },
    }


def _map_enum(mapping: dict[str, str], raw: Optional[str]) -> str:
    if not raw:
        return "未知"
    return mapping.get(raw, raw)
