import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from apps.api.schemas import OrderLogisticsData
from apps.api.support.errors import IntegrationError
from apps.api.support.integration import IntegrationAdapter, map_to_tool_error_code
from apps.api.support.responses import ToolResponse

logger = logging.getLogger("ai_support_delivery.tool")


class OrderLogisticsService:
    """Order/logistics query service backed by mock OMS data.

    All read calls pass through :class:`IntegrationAdapter` to demonstrate
    timeout, retry, circuit-breaker and error-mapping behavior.
    """

    def __init__(
        self,
        records: dict[str, dict[str, Any]],
        *,
        adapter: Optional[IntegrationAdapter] = None,
    ) -> None:
        self.records = records
        self.adapter = adapter or IntegrationAdapter(system="oms")

    @classmethod
    def from_default_data(cls) -> "OrderLogisticsService":
        path = Path(__file__).parents[3] / "data" / "mock" / "orders.json"
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)
        return cls({record["order_id"]: record for record in payload})

    def query(self, order_id: str, user_id: str, trace_id: str) -> ToolResponse:
        started_at = datetime.now().timestamp()

        def _do_query() -> ToolResponse:
            record = self.records.get(order_id)
            if record is None:
                return self._failure(trace_id, "404_ORDER_NOT_FOUND", "未找到该订单，无法确认物流状态。", started_at)
            if record["anonymous_user_id"] != user_id:
                return self._failure(trace_id, "403_ORDER_FORBIDDEN", "无权查询该订单。", started_at)

            data = OrderLogisticsData.model_validate(record["logistics"])
            result = ToolResponse.success_result(data.model_dump(mode="json"), trace_id, "已查询到最新物流状态。")
            self._log(trace_id, order_id, True, None, started_at)
            return result

        try:
            return self.adapter.call(_do_query, read_only=True)
        except IntegrationError as exc:
            code, status, handoff = map_to_tool_error_code(exc)
            self._log(trace_id, None, False, code, started_at)
            return ToolResponse.failure(trace_id, code, str(exc), status, handoff=handoff)

    def _failure(self, trace_id: str, code: str, message: str, started_at: float) -> ToolResponse:
        # 只记录脱敏订单标识和结果，不记录用户身份或地址等敏感字段。
        self._log(trace_id, None, False, code, started_at)
        status = 404 if code == "404_ORDER_NOT_FOUND" else 403
        return ToolResponse.failure(trace_id, code, message, status)

    @staticmethod
    def _log(trace_id: str, order_id: Optional[str], success: bool, error_code: Optional[str], started_at: float) -> None:
        logger.info(
            "tool_call",
            extra={
                "event": "tool_call",
                "tool_name": "query_order_logistics",
                "trace_id": trace_id,
                "order_id": order_id,
                "success": success,
                "error_code": error_code,
                "duration_ms": round((datetime.now().timestamp() - started_at) * 1000, 2),
            },
        )
