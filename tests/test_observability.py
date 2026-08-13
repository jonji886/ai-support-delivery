from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)
SUPERVISOR = {"X-Role": "supervisor"}


def test_assist_trace_can_be_replayed_as_parent_child_chain() -> None:
    response = client.post(
        "/assist",
        json={"message": "帮我查下包裹", "order_id": "OD202608001"},
        headers={"X-User-Id": "user-demo-001"},
    )
    trace_id = response.json()["trace_id"]
    assert response.headers["X-Trace-Id"] == trace_id
    assert client.get(f"/admin/traces/{trace_id}").status_code == 403

    replay = client.get(f"/admin/traces/{trace_id}", headers=SUPERVISOR)
    assert replay.status_code == 200
    body = replay.json()
    assert body["trace"]["status"] == "ok"
    assert body["trace"]["route"] == "/assist"
    spans = {span["name"]: span for span in body["spans"]}
    assert "graph.load_context" in spans
    assert "graph.classify_intent" in spans
    assert "graph.query_logistics" in spans
    assert "tool.query_order_logistics" in spans
    assert spans["tool.query_order_logistics"]["parent_span_id"] == spans["graph.query_logistics"]["span_id"]
    assert all(span["duration_ms"] >= 0 for span in body["spans"])


def test_handled_failure_is_visible_in_trace_and_failure_analysis() -> None:
    response = client.post("/assist", json={"message": "量子传送规则是什么？"})
    trace_id = response.json()["trace_id"]
    replay = client.get(f"/admin/traces/{trace_id}", headers=SUPERVISOR).json()
    failed = [span for span in replay["spans"] if span["status"] == "error"]
    assert any(span["name"] == "rag.search_policy" for span in failed)
    assert any(span["error_code"] == "404_POLICY_NOT_FOUND" for span in failed)

    summary = client.get("/admin/observability/summary?window_minutes=60", headers=SUPERVISOR)
    assert summary.status_code == 200
    data = summary.json()
    assert data["request_count"] >= 2
    assert data["request_latency_ms"]["p95"] >= 0
    assert any(item["operation"] == "rag.search_policy" for item in data["operations"])
    assert data["errors_by_code"]["404_POLICY_NOT_FOUND"] >= 1
    assert data["slowest_traces"]
    assert any(item["trace_id"] == trace_id and item["operation"] == "rag.search_policy" for item in data["recent_failed_spans"])


def test_unhandled_exception_returns_trace_id_and_failed_root(monkeypatch) -> None:
    from apps.api.main import service

    def explode(*args, **kwargs):
        raise RuntimeError("simulated logistics outage")

    monkeypatch.setattr(service, "query", explode)
    response = client.post(
        "/assist",
        json={"message": "订单物流到哪里了", "order_id": "OD202608001"},
        headers={"X-User-Id": "user-demo-001"},
    )
    assert response.status_code == 500
    trace_id = response.json()["trace_id"]
    assert response.headers["X-Trace-Id"] == trace_id
    replay = client.get(f"/admin/traces/{trace_id}", headers=SUPERVISOR).json()
    assert replay["trace"]["status"] == "error"
    assert replay["trace"]["error_code"] == "500_INTERNAL_ERROR"
    assert replay["trace"]["error_type"] == "RuntimeError"
    assert replay["trace"]["error_message"] is None
    assert any(frame["function"] == "explode" for frame in replay["trace"]["attributes"]["exception.stacktrace"])
    assert any(span["name"] == "tool.query_order_logistics" and span["status"] == "error" for span in replay["spans"])


def test_dynamic_resource_identifier_is_not_persisted_as_route() -> None:
    response = client.get(
        "/tools/tickets/TK-SENSITIVE-DEMO-ID",
        headers={"X-User-Id": "user-demo-001"},
    )
    trace_id = response.headers["X-Trace-Id"]
    replay = client.get(f"/admin/traces/{trace_id}", headers=SUPERVISOR).json()
    assert replay["trace"]["route"] == "/tools/tickets/{ticket_id}"
    assert "TK-SENSITIVE-DEMO-ID" not in replay["trace"]["name"]
