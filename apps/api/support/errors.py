"""Unified integration error model.

External system failures must not leak raw exceptions to the Agent or Skill
layer. This module defines a small, explicit error hierarchy that the
Integration Layer maps underlying failures into. Skills consume these errors
to decide retry, handoff, or controlled fallback.
"""

from enum import Enum
from typing import Optional


class IntegrationErrorType(str, Enum):
    """Standard error categories for all external system interactions."""

    EXTERNAL_TIMEOUT = "EXTERNAL_TIMEOUT"
    EXTERNAL_UNAVAILABLE = "EXTERNAL_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    BUSINESS_CONFLICT = "BUSINESS_CONFLICT"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"


class IntegrationError(Exception):
    """Base error for all external system failures.

    Attributes:
        error_type: Standard category for routing decisions.
        system: Name of the external system (e.g. ``oms``, ``logistics``).
        retryable: Whether the caller should retry this operation.
        status_code: Suggested HTTP status for the Tool response.
    """

    def __init__(
        self,
        error_type: IntegrationErrorType,
        system: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int = 503,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.system = system
        self.retryable = retryable
        self.status_code = status_code

    @property
    def error_code(self) -> str:
        return f"{self.error_type.value}"


class ExternalTimeoutError(IntegrationError):
    def __init__(self, system: str, timeout_ms: float) -> None:
        super().__init__(
            IntegrationErrorType.EXTERNAL_TIMEOUT,
            system,
            f"{system} 请求超时（{timeout_ms:.0f}ms），已停止自动处理。",
            retryable=True,
            status_code=504,
        )


class ExternalUnavailableError(IntegrationError):
    def __init__(self, system: str, detail: Optional[str] = None) -> None:
        suffix = f"：{detail}" if detail else ""
        super().__init__(
            IntegrationErrorType.EXTERNAL_UNAVAILABLE,
            system,
            f"{system} 服务不可用{suffix}，已停止自动处理。",
            retryable=True,
            status_code=503,
        )


class RateLimitedError(IntegrationError):
    def __init__(self, system: str) -> None:
        super().__init__(
            IntegrationErrorType.RATE_LIMITED,
            system,
            f"{system} 请求被限流，请稍后重试或转人工。",
            retryable=True,
            status_code=429,
        )


class UnauthorizedError(IntegrationError):
    def __init__(self, system: str) -> None:
        super().__init__(
            IntegrationErrorType.UNAUTHORIZED,
            system,
            f"{system} 认证失败，请检查凭证配置。",
            retryable=False,
            status_code=401,
        )


class InvalidResponseError(IntegrationError):
    def __init__(self, system: str, detail: Optional[str] = None) -> None:
        suffix = f"：{detail}" if detail else ""
        super().__init__(
            IntegrationErrorType.INVALID_RESPONSE,
            system,
            f"{system} 返回了无法解析的响应{suffix}。",
            retryable=False,
            status_code=502,
        )


class BusinessConflictError(IntegrationError):
    def __init__(self, system: str, detail: str) -> None:
        super().__init__(
            IntegrationErrorType.BUSINESS_CONFLICT,
            system,
            f"{system} 业务冲突：{detail}",
            retryable=False,
            status_code=409,
        )


class CircuitOpenError(IntegrationError):
    def __init__(self, system: str) -> None:
        super().__init__(
            IntegrationErrorType.CIRCUIT_OPEN,
            system,
            f"{system} 熔断器已开启，该服务暂时不可用，请转人工处理。",
            retryable=False,
            status_code=503,
        )
