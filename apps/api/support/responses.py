import uuid
from typing import Any, Optional

from pydantic import BaseModel


def new_trace_id() -> str:
    from apps.api.support.observability import current_trace_id

    return current_trace_id() or uuid.uuid4().hex


class ToolResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error_code: Optional[str] = None
    message: str
    trace_id: str
    http_status: int = 200
    handoff: bool = False

    @classmethod
    def success_result(cls, data: Any, trace_id: str, message: str) -> "ToolResponse":
        return cls(success=True, data=data, message=message, trace_id=trace_id)

    @classmethod
    def failure(cls, trace_id: str, error_code: str, message: str, http_status: int = 400, handoff: bool = True) -> "ToolResponse":
        return cls(
            success=False,
            error_code=error_code,
            message=message,
            trace_id=trace_id,
            http_status=http_status,
            handoff=handoff,
        )
