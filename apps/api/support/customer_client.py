"""HTTP client for the customer systems (OMS / Logistics).

Agent 侧服务通过本客户端访问客户系统，**不再直接读取 mock JSON 文件**。
集成边界：Service -> IntegrationAdapter(超时/重试/熔断) -> CustomerSystemClient -> HTTP -> 客户系统。

错误契约：
* 404 订单不存在   -> :class:`OrderNotFoundError`
* 403 无权访问     -> :class:`OrderForbiddenError`
* 429 限流         -> :class:`RateLimitedError`（可重试）
* 5xx / 网络错误    -> :class:`ExternalUnavailableError`
* 超时             -> :class:`ExternalTimeoutError`

本地演示可设置 ``MOCK_CUSTOMER_FAULT=timeout`` 或 ``MOCK_CUSTOMER_SLOW_MS``
将故障注入请求转发到 Mock Customer Systems；生产环境不应启用这些变量。

``OrderNotFoundError`` / ``OrderForbiddenError`` 是业务性错误（非 Infrastructure 故障），
因此继承自 :class:`Exception` 而非 ``IntegrationError``，不会被 Adapter 当作上游故障处理。
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

from apps.api.support.errors import (
    ExternalTimeoutError,
    ExternalUnavailableError,
    RateLimitedError,
)


class OrderNotFoundError(Exception):
    """The order does not exist in the customer OMS."""


class OrderForbiddenError(Exception):
    """The user is not authorized to access this order."""


class CustomerSystemClient:
    """Minimal HTTP client for the mock customer systems."""

    def __init__(self, base_url: str, *, timeout_ms: int = 3000, system: str = "oms"):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_ms / 1000.0
        self.system = system
        # Local/demo-only fault forwarding. Explicit per-request headers still
        # take precedence, so tests and operators can target one call.
        self.fault_mode = os.getenv("MOCK_CUSTOMER_FAULT", "").strip()
        self.slow_ms = os.getenv("MOCK_CUSTOMER_SLOW_MS", "").strip()
        self._http = httpx.Client(timeout=self.timeout)

    def fetch_order(self, order_id: str, user_id: str, *, headers: Optional[dict] = None) -> dict:
        """GET /oms/orders/{order_id} — 订单主数据（客户字段命名）。"""
        return self._get(f"/oms/orders/{order_id}", user_id, headers=headers)

    def fetch_tracking(self, order_id: str, user_id: str, *, headers: Optional[dict] = None) -> dict:
        """GET /logistics/orders/{order_id}/tracking — 物流追踪（客户字段命名）。"""
        return self._get(f"/logistics/orders/{order_id}/tracking", user_id, headers=headers)

    def _get(self, path: str, user_id: str, *, headers: Optional[dict] = None) -> dict:
        request_headers = {"X-User-Id": user_id}
        if self.fault_mode:
            request_headers["X-Fault-Inject"] = self.fault_mode
        if self.slow_ms:
            request_headers["X-Mock-Slow-Ms"] = self.slow_ms
        if headers:
            request_headers.update(headers)
        try:
            response = self._http.get(f"{self.base_url}{path}", headers=request_headers)
        except httpx.TimeoutException as exc:
            raise ExternalTimeoutError(self.system, timeout_ms=self.timeout * 1000) from exc
        except httpx.TransportError as exc:
            raise ExternalUnavailableError(
                self.system, detail=f"cannot reach customer system: {exc}"
            ) from exc

        if response.status_code == 404:
            raise OrderNotFoundError(f"{path}: order not found")
        if response.status_code == 403:
            raise OrderForbiddenError(f"{path}: access denied")
        if response.status_code == 429:
            raise RateLimitedError(self.system)
        if response.status_code >= 500:
            raise ExternalUnavailableError(self.system, detail=f"upstream {response.status_code}")
        if response.status_code != 200:
            raise ExternalUnavailableError(
                self.system, detail=f"unexpected upstream status {response.status_code}"
            )
        return response.json()
