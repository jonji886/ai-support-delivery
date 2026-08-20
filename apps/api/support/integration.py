"""Integration Layer: controlled gateway between Skills and external systems.

This module provides:

* :class:`CircuitBreaker` – lightweight CLOSED/OPEN/HALF_OPEN state machine.
* :class:`FaultInjector` – deterministic, config-driven latency/failure injection.
* :class:`IntegrationAdapter` – wraps external calls with timeout, retry,
  exponential backoff, circuit-breaker, and unified error mapping.

Design goals:

1. External system failures must never produce fake success.
2. Raw exceptions (timeout, connection error) must be mapped to
   :mod:`apps.api.support.errors` before reaching the Skill layer.
3. Fault injection is deterministic (not random) to avoid CI flakiness.
4. No heavy infrastructure framework – this is a small, readable implementation
   suitable for a POC that demonstrates enterprise integration reliability.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

from apps.api.support.errors import (
    CircuitOpenError,
    ExternalTimeoutError,
    ExternalUnavailableError,
    IntegrationError,
)

logger = logging.getLogger("ai_support_delivery.integration")

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreaker:
    """Minimal circuit breaker for a single external system.

    The breaker transitions:

    * CLOSED → OPEN: when ``failure_threshold`` consecutive failures occur.
    * OPEN → HALF_OPEN: after ``recovery_timeout`` seconds have elapsed.
    * HALF_OPEN → CLOSED: on first success; HALF_OPEN → OPEN: on first failure.

    All state is in-memory and per-process; production should use a shared
    store (e.g. Redis) for multi-instance coordination.
    """

    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 30.0

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
            return self._state

    def allow(self) -> bool:
        """Return True if a call is permitted; False if the circuit is open."""
        return self.state != CircuitState.OPEN

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit_breaker_opened",
                    extra={
                        "event": "circuit_breaker",
                        "system": self.name,
                        "state": self._state.value,
                        "failure_count": self._failure_count,
                    },
                )
            elif self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN

    def reset(self) -> None:
        """Reset to CLOSED – primarily for testing."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0


@dataclass
class FaultInjectionConfig:
    """Deterministic fault injection for a single external system.

    Controlled by environment variables ``MOCK_<SYSTEM>_LATENCY_MS`` and
    ``MOCK_<SYSTEM>_FAILURE_RATE``.  ``failure_rate`` is 0..1; the injector
    uses a simple counter rather than randomness so tests are deterministic.

    Example::

        MOCK_OMS_LATENCY_MS=3000
        MOCK_OMS_FAILURE_RATE=0.5
    """

    system: str
    latency_ms: float = 0.0
    failure_every_n: int = 0  # 0 = disabled; N = fail every Nth call
    _call_count: int = field(default=0, init=False)

    @classmethod
    def from_env(cls, system: str) -> "FaultInjectionConfig":
        prefix = system.upper()
        latency = float(os.getenv(f"MOCK_{prefix}_LATENCY_MS", "0"))
        rate = float(os.getenv(f"MOCK_{prefix}_FAILURE_RATE", "0"))
        # Convert rate to "fail every Nth call" for deterministic behavior.
        # rate=0.5 → fail every 2nd call; rate=0.33 → every 3rd; rate=1.0 → every call.
        if rate <= 0:
            return cls(system=system, latency_ms=latency, failure_every_n=0)
        every_n = max(1, round(1.0 / rate))
        return cls(system=system, latency_ms=latency, failure_every_n=every_n)

    def inject(self) -> None:
        """Apply configured latency and decide if this call should fail.

        Raises ``ExternalUnavailableError`` when the deterministic counter
        indicates a fault should be injected.
        """
        if self.latency_ms > 0:
            time.sleep(self.latency_ms / 1000.0)
        if self.failure_every_n > 0:
            self._call_count += 1
            if self._call_count % self.failure_every_n == 0:
                raise ExternalUnavailableError(
                    self.system,
                    detail=f"注入故障（第 {self._call_count} 次调用）",
                )


@dataclass
class IntegrationAdapter:
    """Wraps an external call with timeout, retry, and circuit breaker.

    Usage::

        adapter = IntegrationAdapter(
            system="oms",
            timeout_ms=3000,
            max_retries=1,
            backoff_base_ms=200,
        )
        result = adapter.call(lambda: service.query(order_id))

    The callback is expected to return a ``ToolResponse`` or raise an
    exception. Integration-layer exceptions are already mapped; unknown
    exceptions are wrapped into ``ExternalUnavailableError``.
    """

    system: str
    timeout_ms: float = 3000.0
    max_retries: int = 1
    backoff_base_ms: float = 200.0
    circuit: Optional[CircuitBreaker] = None
    fault: Optional[FaultInjectionConfig] = None

    def __post_init__(self) -> None:
        if self.circuit is None:
            self.circuit = CircuitBreaker(name=self.system)
        if self.fault is None:
            self.fault = FaultInjectionConfig.from_env(self.system)

    def call(self, operation: Callable[[], T], *, read_only: bool = True) -> T:
        """Execute ``operation`` with integration reliability controls.

        Args:
            operation: A callable that performs the external call.
            read_only: Read operations are retried on transient failures;
                write operations are never retried automatically.

        Returns:
            The result of ``operation``.

        Raises:
            CircuitOpenError: If the circuit breaker is open.
            IntegrationError: If the call fails after retries.
        """
        if self.circuit and not self.circuit.allow():
            raise CircuitOpenError(self.system)

        last_error: Optional[IntegrationError] = None
        attempts = 1 + (self.max_retries if read_only else 0)

        for attempt in range(attempts):
            try:
                if self.fault:
                    self.fault.inject()
                result = self._execute_with_timeout(operation)
                if self.circuit:
                    self.circuit.record_success()
                return result
            except IntegrationError as exc:
                last_error = exc
                if self.circuit:
                    self.circuit.record_failure()
                if attempt < attempts - 1 and exc.retryable:
                    backoff = self.backoff_base_ms * (2 ** attempt)
                    logger.info(
                        "integration_retry",
                        extra={
                            "event": "integration_retry",
                            "system": self.system,
                            "attempt": attempt + 1,
                            "backoff_ms": backoff,
                            "error_type": exc.error_type.value,
                        },
                    )
                    time.sleep(backoff / 1000.0)
                else:
                    raise
            except Exception as exc:
                # Map unknown exceptions to a standard error.
                mapped = ExternalUnavailableError(self.system, detail=type(exc).__name__)
                last_error = mapped
                if self.circuit:
                    self.circuit.record_failure()
                raise mapped from exc

        assert last_error is not None
        raise last_error

    def _execute_with_timeout(self, operation: Callable[[], T]) -> T:
        """Execute operation with a simple deadline check.

        For synchronous POC services this uses a thread-based timeout.
        Production async services should use ``asyncio.wait_for``.
        """
        if self.timeout_ms <= 0:
            return operation()

        result_holder: list[Any] = []
        error_holder: list[BaseException] = []

        def run() -> None:
            try:
                result_holder.append(operation())
            except BaseException as exc:
                error_holder.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(timeout=self.timeout_ms / 1000.0)

        if thread.is_alive():
            raise ExternalTimeoutError(self.system, self.timeout_ms)
        if error_holder:
            exc = error_holder[0]
            if isinstance(exc, IntegrationError):
                raise exc
            raise exc
        if result_holder:
            return result_holder[0]
        raise ExternalUnavailableError(self.system, detail="empty result")


def map_to_tool_error_code(exc: IntegrationError) -> tuple[str, int, bool]:
    """Map an IntegrationError to (error_code, http_status, handoff).

    This keeps Skill/Tool layers decoupled from the specific exception types.
    """
    mapping = {
        "EXTERNAL_TIMEOUT": ("504_EXTERNAL_TIMEOUT", 504, True),
        "EXTERNAL_UNAVAILABLE": ("503_EXTERNAL_UNAVAILABLE", 503, True),
        "RATE_LIMITED": ("429_RATE_LIMITED", 429, True),
        "UNAUTHORIZED": ("401_EXTERNAL_UNAUTHORIZED", 401, False),
        "INVALID_RESPONSE": ("502_INVALID_RESPONSE", 502, True),
        "BUSINESS_CONFLICT": ("409_BUSINESS_CONFLICT", 409, False),
        "CIRCUIT_OPEN": ("503_CIRCUIT_OPEN", 503, True),
    }
    return mapping.get(exc.error_type.value, ("503_EXTERNAL_ERROR", 503, True))
