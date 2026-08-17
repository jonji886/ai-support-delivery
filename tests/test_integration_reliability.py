"""Integration reliability tests.

These tests verify that the Agent correctly handles external system failures:
timeout, retry, circuit breaker, error mapping, handoff on failure, idempotency,
and unauthorized tool blocking. All fault injection is deterministic.
"""

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.support.errors import (
    CircuitOpenError,
    ExternalTimeoutError,
    ExternalUnavailableError,
)
from apps.api.support.integration import (
    CircuitBreaker,
    CircuitState,
    FaultInjectionConfig,
    IntegrationAdapter,
    map_to_tool_error_code,
)
from apps.api.support.responses import ToolResponse

client = TestClient(app)


# ---------------------------------------------------------------------------
# Circuit Breaker unit tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_starts_in_closed_state(self) -> None:
        cb = CircuitBreaker(name="oms")
        assert cb.state == CircuitState.CLOSED
        assert cb.allow() is True

    def test_opens_after_threshold_failures(self) -> None:
        cb = CircuitBreaker(name="oms", failure_threshold=3, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow() is False

    def test_prevents_repeated_calls_when_open(self) -> None:
        cb = CircuitBreaker(name="oms", failure_threshold=2, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # All subsequent calls should be blocked
        assert cb.allow() is False
        assert cb.allow() is False

    def test_transitions_to_half_open_after_recovery_timeout(self) -> None:
        cb = CircuitBreaker(name="oms", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        # Success in half-open should close the circuit
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens_circuit(self) -> None:
        cb = CircuitBreaker(name="oms", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# Fault Injection tests
# ---------------------------------------------------------------------------


class TestFaultInjection:
    def test_latency_injection(self) -> None:
        config = FaultInjectionConfig(system="oms", latency_ms=50, failure_every_n=0)
        start = time.monotonic()
        config.inject()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.04  # at least ~50ms

    def test_deterministic_failure_injection(self) -> None:
        config = FaultInjectionConfig(system="oms", latency_ms=0, failure_every_n=3)
        # First two calls should succeed
        config.inject()
        config.inject()
        # Third call should fail
        with pytest.raises(ExternalUnavailableError):
            config.inject()
        # Fourth and fifth succeed, sixth fails
        config.inject()
        config.inject()
        with pytest.raises(ExternalUnavailableError):
            config.inject()

    def test_disabled_by_default(self) -> None:
        config = FaultInjectionConfig(system="oms", latency_ms=0, failure_every_n=0)
        # Should not raise
        config.inject()


# ---------------------------------------------------------------------------
# Integration Adapter tests
# ---------------------------------------------------------------------------


class TestIntegrationAdapter:
    def test_successful_call_returns_result(self) -> None:
        adapter = IntegrationAdapter(system="oms", timeout_ms=1000, max_retries=0)
        result = adapter.call(lambda: "success", read_only=True)
        assert result == "success"

    def test_timeout_is_mapped_to_domain_error(self) -> None:
        adapter = IntegrationAdapter(system="oms", timeout_ms=100, max_retries=0)

        def slow_operation() -> str:
            time.sleep(0.5)
            return "should not reach"

        with pytest.raises(ExternalTimeoutError):
            adapter.call(slow_operation, read_only=True)

    def test_read_only_operation_is_retried(self) -> None:
        call_count = [0]
        adapter = IntegrationAdapter(
            system="oms",
            timeout_ms=5000,
            max_retries=2,
            backoff_base_ms=10,
        )

        def fail_then_succeed() -> str:
            call_count[0] += 1
            if call_count[0] < 2:
                raise ExternalUnavailableError("oms", "transient")
            return "recovered"

        result = adapter.call(fail_then_succeed, read_only=True)
        assert result == "recovered"
        assert call_count[0] == 2

    def test_write_operation_is_not_retried(self) -> None:
        call_count = [0]
        adapter = IntegrationAdapter(
            system="ticket",
            timeout_ms=5000,
            max_retries=2,
            backoff_base_ms=10,
        )

        def always_fail() -> str:
            call_count[0] += 1
            raise ExternalUnavailableError("ticket", "persistent")

        with pytest.raises(ExternalUnavailableError):
            adapter.call(always_fail, read_only=False)
        assert call_count[0] == 1  # no retries for write operations

    def test_circuit_open_blocks_call(self) -> None:
        cb = CircuitBreaker(name="oms", failure_threshold=1, recovery_timeout=60)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        adapter = IntegrationAdapter(system="oms", circuit=cb, max_retries=0)
        with pytest.raises(CircuitOpenError):
            adapter.call(lambda: "should not reach", read_only=True)

    def test_unknown_exception_is_mapped(self) -> None:
        adapter = IntegrationAdapter(system="oms", max_retries=0, backoff_base_ms=1)

        def raise_value_error() -> str:
            raise ValueError("unexpected")

        with pytest.raises(ExternalUnavailableError):
            adapter.call(raise_value_error, read_only=True)


# ---------------------------------------------------------------------------
# Error mapping tests
# ---------------------------------------------------------------------------


class TestErrorMapping:
    def test_timeout_maps_to_504(self) -> None:
        exc = ExternalTimeoutError("oms", 3000)
        code, status, handoff = map_to_tool_error_code(exc)
        assert code == "504_EXTERNAL_TIMEOUT"
        assert status == 504
        assert handoff is True

    def test_unavailable_maps_to_503(self) -> None:
        exc = ExternalUnavailableError("oms")
        code, status, handoff = map_to_tool_error_code(exc)
        assert code == "503_EXTERNAL_UNAVAILABLE"
        assert status == 503
        assert handoff is True

    def test_circuit_open_maps_to_503(self) -> None:
        exc = CircuitOpenError("oms")
        code, status, handoff = map_to_tool_error_code(exc)
        assert code == "503_CIRCUIT_OPEN"
        assert status == 503
        assert handoff is True


# ---------------------------------------------------------------------------
# End-to-end integration tests through the API
# ---------------------------------------------------------------------------


class TestEndToEndReliability:
    def test_external_failure_does_not_generate_fake_success(self) -> None:
        """When the OMS fails, the API must return failure, not fake data."""
        from apps.api.main import service

        original_adapter = service.adapter
        fault_config = FaultInjectionConfig(system="oms", latency_ms=0, failure_every_n=1)
        service.adapter = IntegrationAdapter(
            system="oms",
            timeout_ms=5000,
            max_retries=0,
            fault=fault_config,
        )
        try:
            response = client.post(
                "/tools/query-order-logistics",
                json={"order_id": "OD202608001"},
                headers={"X-User-Id": "user-demo-001"},
            )
            body = response.json()
            assert body["success"] is False
            assert body["error_code"] == "503_EXTERNAL_UNAVAILABLE"
            assert body["handoff"] is True
        finally:
            service.adapter = original_adapter

    def test_external_failure_can_trigger_handoff(self) -> None:
        """When a Tool fails, /assist should hand off to human, not fabricate."""
        from apps.api.main import service

        original_adapter = service.adapter
        fault_config = FaultInjectionConfig(system="oms", latency_ms=0, failure_every_n=1)
        service.adapter = IntegrationAdapter(
            system="oms",
            timeout_ms=5000,
            max_retries=0,
            fault=fault_config,
        )
        try:
            response = client.post(
                "/assist",
                json={"message": "订单到哪里了？", "order_id": "OD202608001"},
                headers={"X-User-Id": "user-demo-001"},
            )
            body = response.json()
            # The logistics query should fail and result in a failure/handoff
            assert body["success"] is False
            assert body["handoff"] is True
        finally:
            service.adapter = original_adapter

    def test_duplicate_write_request_is_idempotent(self) -> None:
        """Same idempotency key must not create duplicate tickets."""
        key = "test-idempotency-" + str(time.time())
        response1 = client.post(
            "/tools/create-service-ticket",
            json={
                "conversation_summary": "测试幂等",
                "category": "complaint_or_dispute",
                "priority": "high",
                "order_id": "OD202608001",
                "idempotency_key": key,
            },
            headers={"X-User-Id": "user-demo-001"},
        )
        response2 = client.post(
            "/tools/create-service-ticket",
            json={
                "conversation_summary": "测试幂等",
                "category": "complaint_or_dispute",
                "priority": "high",
                "order_id": "OD202608001",
                "idempotency_key": key,
            },
            headers={"X-User-Id": "user-demo-001"},
        )
        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response1.json()["data"]["ticket_id"] == response2.json()["data"]["ticket_id"]

    def test_unauthorized_tool_call_is_blocked(self) -> None:
        """Logistics skill must not be able to call submit_return_application."""
        from apps.api.main import skill_executor
        from apps.api.skills.contracts import SkillExecutionContext, SkillResult
        from apps.api.skills.executor import SkillExecutor
        from apps.api.support.observability import TraceStore

        executor = SkillExecutor.__new__(SkillExecutor)
        executor.registry = skill_executor.registry
        executor.observability = TraceStore(":memory:")

        callback_called = [False]

        def handler(context, tools):
            def callback():
                callback_called[0] = True
                return ToolResponse.success_result({}, context.trace_id, "不应执行")

            result = tools.call("submit_return_application", "write", callback)
            return SkillResult.from_tool("logistics_inquiry", "logistics", "submit_return_application", result)

        outcome = executor.execute(
            "logistics_inquiry",
            SkillExecutionContext(trace_id="test-unauth", intent="logistics"),
            handler,
        )
        assert callback_called[0] is False
        assert outcome.result.error_code == "500_SKILL_TOOL_POLICY_VIOLATION"

    def test_circuit_breaker_opens_after_threshold(self) -> None:
        """Circuit breaker should open after consecutive failures."""
        from apps.api.main import service

        original_adapter = service.adapter
        cb = CircuitBreaker(name="oms", failure_threshold=3, recovery_timeout=60)
        fault_config = FaultInjectionConfig(system="oms", latency_ms=0, failure_every_n=1)
        service.adapter = IntegrationAdapter(
            system="oms",
            timeout_ms=5000,
            max_retries=0,
            circuit=cb,
            fault=fault_config,
        )
        try:
            # First 3 calls should fail and open the circuit
            for _ in range(3):
                client.post(
                    "/tools/query-order-logistics",
                    json={"order_id": "OD202608001"},
                    headers={"X-User-Id": "user-demo-001"},
                )
            assert cb.state == CircuitState.OPEN

            # Subsequent call should be blocked by circuit breaker
            response = client.post(
                "/tools/query-order-logistics",
                json={"order_id": "OD202608001"},
                headers={"X-User-Id": "user-demo-001"},
            )
            assert response.json()["error_code"] == "503_CIRCUIT_OPEN"
        finally:
            service.adapter = original_adapter

    def test_external_timeout_is_retried_then_fails_gracefully(self) -> None:
        """Read operations should retry on timeout, then fail with handoff."""
        call_count = [0]
        adapter = IntegrationAdapter(
            system="oms",
            timeout_ms=100,
            max_retries=1,
            backoff_base_ms=10,
        )

        def slow_operation():
            call_count[0] += 1
            time.sleep(0.3)
            return "should not reach"

        with pytest.raises(ExternalTimeoutError):
            adapter.call(slow_operation, read_only=True)
        assert call_count[0] == 2  # initial + 1 retry

    def test_external_failure_is_mapped_to_domain_error(self) -> None:
        """Raw exceptions must be mapped to standard error codes."""
        from apps.api.main import service

        original_adapter = service.adapter

        def raise_connection_error():
            raise ConnectionError("connection refused")

        adapter = IntegrationAdapter(system="oms", timeout_ms=5000, max_retries=0)
        service.adapter = adapter
        try:
            with patch.object(service, "records", {}):
                # Override the adapter's call to use our failing function
                original_call = adapter.call

                def failing_call(operation, *, read_only=True):
                    return original_call(lambda: raise_connection_error(), read_only=read_only)

                adapter.call = failing_call
                response = client.post(
                    "/tools/query-order-logistics",
                    json={"order_id": "OD202608001"},
                    headers={"X-User-Id": "user-demo-001"},
                )
                body = response.json()
                assert body["success"] is False
                assert body["error_code"] == "503_EXTERNAL_UNAVAILABLE"
        finally:
            service.adapter = original_adapter
