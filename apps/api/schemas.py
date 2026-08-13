from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class QueryOrderLogisticsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(pattern=r"^OD\d{9}$", description="匿名订单号")


class CheckReturnEligibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(pattern=r"^OD\d{9}$", description="匿名订单号")
    return_reason: str = Field(min_length=2, max_length=100)


class SearchPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=500)
    region: str = Field(default="US", min_length=2, max_length=20)


class CreateServiceTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_summary: str = Field(min_length=2, max_length=2000)
    category: str = Field(min_length=2, max_length=50)
    priority: str = Field(pattern=r"^(normal|high|urgent)$")
    order_id: Optional[str] = Field(default=None, pattern=r"^OD\d{9}$")
    idempotency_key: str = Field(min_length=8, max_length=100)


class HandoffHumanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_summary: str = Field(min_length=2, max_length=2000)
    reason: str = Field(min_length=2, max_length=200)
    category: str = Field(default="human_handoff", min_length=2, max_length=50)
    priority: str = Field(default="high", pattern=r"^(normal|high|urgent)$")
    order_id: Optional[str] = Field(default=None, pattern=r"^OD\d{9}$")
    idempotency_key: str = Field(min_length=8, max_length=100)


class SubmitReturnApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(pattern=r"^OD\d{9}$")
    return_reason: str = Field(min_length=2, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=100)


class ReviewReturnApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern=r"^(approved|rejected)$")
    reason: Optional[str] = Field(default=None, max_length=200)


class ResolveTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern=r"^(已解决|待补充信息|已升级主管)$")
    reply: str = Field(min_length=2, max_length=1000)


class AssistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=2, max_length=1000)
    order_id: Optional[str] = Field(default=None, pattern=r"^OD\d{9}$")
    return_reason: Optional[str] = Field(default=None, max_length=100)
    session_id: Optional[str] = Field(default=None, min_length=8, max_length=100)


class ReturnEligibilityData(BaseModel):
    order_id: str
    eligible: bool
    decision: str
    rule_version: str
    basis: str
    next_steps: list[str]
    requires_human: bool


class LogisticsEvent(BaseModel):
    occurred_at: datetime
    location: str
    description: str


class OrderLogisticsData(BaseModel):
    order_id: str
    order_status: str
    carrier: str
    latest_event: LogisticsEvent
    exception: bool
    estimated_arrival: Optional[datetime] = None


class ErrorDetail(BaseModel):
    code: str
    retryable: bool = False


class ToolResponseModel(BaseModel):
    success: bool
    data: Optional[Any] = None
    error_code: Optional[str] = None
    message: str
    trace_id: str
