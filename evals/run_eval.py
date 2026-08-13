"""Run all fixed cases against the local FastAPI application."""
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from apps.api.main import app, events as app_events

client = TestClient(app)
cases_path = Path(__file__).with_name("mvp-50.jsonl")
cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    results = []
    latencies = []
    run_id = uuid.uuid4().hex[:8]
    for case in cases:
        pre = case["preconditions"]
        headers = {"X-User-Id": pre["user_id"]} if pre.get("user_id") else {}
        started = time.perf_counter()
        if case.get("turns"):
            for turn_index, turn in enumerate(case["turns"]):
                payload = {"message": turn["message"], "session_id": f"eval-{run_id}-{case['case_id']}"}
                if turn.get("order_id"):
                    payload["order_id"] = turn["order_id"]
                if turn.get("return_reason"):
                    payload["return_reason"] = turn["return_reason"]
                response = client.post("/assist", json=payload, headers=headers)
                latencies.append((time.perf_counter() - started) * 1000)
        elif case["expected_intent"] == "return_application":
            response = client.post(
                "/tools/submit-return-application",
                json={"order_id": pre["order_id"], "return_reason": pre["return_reason"], "idempotency_key": "eval-" + case["case_id"]},
                headers=headers,
            )
        else:
            payload = {"message": case["input"], "session_id": f"eval-{run_id}-{case['case_id']}"}
            if pre.get("order_id"):
                payload["order_id"] = pre["order_id"]
            if pre.get("return_reason"):
                payload["return_reason"] = pre["return_reason"]
            response = client.post("/assist", json=payload, headers=headers)
        if not case.get("turns"):
            latencies.append((time.perf_counter() - started) * 1000)
        body = response.json()
        text = json.dumps(body, ensure_ascii=False)
        passed = response.status_code == case["expected_status"]
        if case["expected_fact"]:
            passed = passed and case["expected_fact"] in text
        if case.get("expected_message_contains"):
            passed = passed and case["expected_message_contains"] in body.get("message", "")
        if case.get("expected_ticket_category"):
            data = body.get("data") if isinstance(body.get("data"), dict) else {}
            passed = passed and data.get("category") == case["expected_ticket_category"]
        if case.get("expected_rule_version"):
            data = body.get("data") if isinstance(body.get("data"), dict) else {}
            citations = data.get("citations") or []
            passed = passed and any(item.get("version") == case["expected_rule_version"] for item in citations)
        has_citation = bool(body.get("data", {}).get("citations")) if isinstance(body.get("data"), dict) else False
        passed = passed and has_citation == case["expected_citation"]
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        handoff = bool(body.get("handoff") or data.get("requires_human") or data.get("status") == "待人工处理")
        passed = passed and handoff == case["expected_handoff"]
        # The endpoint is in-process here, so inspect the app event stream to
        # verify that the response came from an allowed controlled Tool.
        tool_names = {event.get("tool_name") for event in app_events.events_for_trace(body.get("trace_id"))}
        passed = passed and bool(tool_names.intersection(case["allowed_tools"]))
        results.append({"case_id": case["case_id"], "passed": passed, "status": response.status_code, "response": body})

    total = len(results)
    passed = sum(item["passed"] for item in results)
    policy_results = [item for item, case in zip(results, cases) if case["expected_intent"] == "policy" and case["expected_citation"]]
    risk_results = [item for item, case in zip(results, cases) if case["expected_handoff"]]
    report = {
        "dataset_version": max((case.get("version", "unknown") for case in cases), default="unknown"), "total_cases": total, "passed_cases": passed,
        "core_scenario_pass_rate": round(passed / total, 4),
        "citation_validity_rate": round(sum(item["passed"] for item in policy_results) / len(policy_results), 4),
        "high_risk_handoff_coverage": round(sum(item["passed"] for item in risk_results) / len(risk_results), 4),
        "p95_latency_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2),
        "tool_success_rate": round(sum(1 for item, case in zip(results, cases) if case["expected_status"] == 200 and item["passed"]) / sum(1 for case in cases if case["expected_status"] == 200), 4),
        "failures": [item for item in results if not item["passed"]],
    }
    Path(__file__).with_name("latest-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from render_acceptance_report import render
    render()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed == total else 1)
if __name__ == "__main__":
    main()
