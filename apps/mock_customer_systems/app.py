"""Mock Customer Systems — HTTP API simulating a customer's backend systems.

SIMULATED / SYNTHETIC: 本服务模拟客户的真实后端系统，全部数据均为合成演示数据，
仅用于本地开发、演示和集成测试，不代表任何真实客户数据。

模拟的两个客户系统：
* OMS（订单管理系统）  : ``GET /oms/orders/{order_id}``
* Logistics（物流系统） : ``GET /logistics/orders/{order_id}/tracking``

字段命名刻意与 Agent 侧内部 schema 不同（如 ``order_no`` vs ``order_id``、
``fulfillment_status`` vs ``order_status``），以验证 Field Mapping 层的工作。

故障注入：通过 ``X-Fault-Inject`` 请求头（或 ``?fault=`` 查询参数）驱动，
取值见 ``apps.mock_customer_systems.faults``。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from apps.mock_customer_systems.faults import apply_fault

app = FastAPI(
    title="Mock Customer Systems (OMS + Logistics)",
    version="0.1.0",
    description="SIMULATED: synthetic customer backend systems for dev/demo/integration tests.",
)

_DATA_ROOT = Path(__file__).resolve().parents[2] / "data" / "mock" / "customer"


def _load(name: str) -> list:
    with (_DATA_ROOT / name).open(encoding="utf-8") as fh:
        return json.load(fh)


_OMS_ORDERS = {item["order_no"]: item for item in _load("oms.json")}
_LOGISTICS = {item["order_no"]: item for item in _load("logistics.json")}

#: Per-route call counters, exposed via /admin/stats so integration tests can
#: prove the Agent really reached the customer systems over HTTP.
_call_counts: dict = defaultdict(int)


def _deny_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


def _authorize(x_user_id: Optional[str], order_no: str) -> Optional[JSONResponse]:
    """Enforce customer-side authentication/authorization semantics."""
    if not x_user_id:
        return _deny_response(401, "MISSING_USER", "缺少 X-User-Id 请求头。")
    if order_no not in _OMS_ORDERS:
        return _deny_response(404, "ORDER_NOT_FOUND", f"订单 {order_no} 不存在。")
    if _OMS_ORDERS[order_no]["customer_ref"] != x_user_id:
        return _deny_response(403, "ORDER_FORBIDDEN", f"用户无权访问订单 {order_no}。")
    return None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mock-customer-systems"}


@app.get("/admin/stats")
def stats() -> dict:
    return {"calls": dict(_call_counts)}


@app.get("/oms/orders/{order_id}")
async def get_order(
    order_id: str,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
):
    injected = await apply_fault(request)
    if injected is not None:
        return injected
    denied = _authorize(x_user_id, order_id)
    if denied is not None:
        return denied
    _call_counts["oms/orders"] += 1
    return _OMS_ORDERS[order_id]


@app.get("/logistics/orders/{order_id}/tracking")
async def get_tracking(
    order_id: str,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
):
    injected = await apply_fault(request)
    if injected is not None:
        return injected
    denied = _authorize(x_user_id, order_id)
    if denied is not None:
        return denied
    if order_id not in _LOGISTICS:
        return _deny_response(404, "TRACKING_NOT_FOUND", f"订单 {order_id} 暂无物流信息。")
    _call_counts["logistics/tracking"] += 1
    return _LOGISTICS[order_id]
