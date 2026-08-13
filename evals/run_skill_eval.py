"""Evaluate Skill selection separately from governed Skill execution."""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_runtime = tempfile.TemporaryDirectory(prefix="skill-eval-")
os.environ["SUPPORT_DB_PATH"] = str(Path(_runtime.name) / "support.db")
os.environ["CONVERSATION_DB_PATH"] = str(Path(_runtime.name) / "conversations.db")
os.environ["EVENTS_DB_PATH"] = str(Path(_runtime.name) / "events.db")
os.environ["OBSERVABILITY_DB_PATH"] = str(Path(_runtime.name) / "observability.db")
os.environ["DEEPSEEK_ENABLED"] = "false"
os.environ["LOG_LEVEL"] = "CRITICAL"

from apps.api.main import app, intent_catalog, skill_registry
from fastapi.testclient import TestClient


def evaluate_selection() -> dict:
    cases = [
        json.loads(line)
        for line in (ROOT / "evals/skill-selection-cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    results = []
    high_risk_total = high_risk_hits = 0
    for case in cases:
        decision = intent_catalog.classify(case["input"], case.get("previous_intent"))
        skill_id = skill_registry.for_intent(decision["intent"]).skill_id
        passed = decision["intent"] == case["expected_intent"] and skill_id == case["expected_skill"]
        if case.get("expected_secondary"):
            passed = passed and case["expected_secondary"] in decision["secondary_intents"]
        if case.get("high_risk"):
            high_risk_total += 1
            high_risk_hit = skill_id == "risk_handoff"
            high_risk_hits += int(high_risk_hit)
            passed = passed and high_risk_hit
        results.append({
            "case_id": case["case_id"], "passed": passed,
            "expected_skill": case["expected_skill"], "actual_skill": skill_id,
            "actual_intent": decision["intent"],
        })
    passed = sum(item["passed"] for item in results)
    return {
        "total_cases": len(results), "passed_cases": passed,
        "selection_accuracy": round(passed / len(results), 4),
        "high_risk_skill_recall": round(high_risk_hits / high_risk_total, 4),
        "failures": [item for item in results if not item["passed"]],
    }


def evaluate_execution() -> dict:
    cases = []
    for skill_id in skill_registry.skill_ids:
        dataset_path = ROOT / skill_registry.get(skill_id).evaluation.dataset
        cases.extend(
            {**json.loads(line), "skill_id": skill_id}
            for line in dataset_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    client = TestClient(app)
    scenarios = {}

    def assist(name, message, *, order_id=None, return_reason=None, user_id=None):
        payload = {"message": message, "session_id": f"skill-eval-{name}"}
        if order_id:
            payload["order_id"] = order_id
        if return_reason:
            payload["return_reason"] = return_reason
        headers = {"X-User-Id": user_id} if user_id else {}
        return client.post("/assist", json=payload, headers=headers)

    scenarios["logistics_success"] = assist("logistics-success", "我的包裹到哪里了", order_id="OD202608001", user_id="user-demo-001")
    scenarios["logistics_missing_order"] = assist("logistics-missing", "我的包裹到哪里了", user_id="user-demo-001")
    scenarios["return_eligibility_success"] = assist("return-success", "这个订单能退吗", order_id="OD202608001", return_reason="尺码不合适", user_id="user-demo-001")
    scenarios["return_missing_reason"] = assist("return-missing", "这个订单能退吗", order_id="OD202608001", user_id="user-demo-001")
    scenarios["return_human_review"] = assist("return-human", "这个订单能退吗", order_id="OD202608001", return_reason="商品质量问题", user_id="user-demo-001")
    scenarios["policy_success"] = assist("policy-success", "海外仓发货多久能到")
    scenarios["policy_no_evidence"] = assist("policy-none", "量子传送规则是什么")
    scenarios["risk_complaint"] = assist("risk-complaint", "一直不退款我要投诉", order_id="OD202608001", user_id="user-demo-001")
    scenarios["risk_payment"] = assist("risk-payment", "帮我修改银行卡收款人", user_id="user-demo-001")
    scenarios["confirmed_write"] = client.post(
        "/tools/submit-return-application",
        json={"order_id":"OD202608001", "return_reason":"尺码不合适", "idempotency_key":"skill-eval-write-01"},
        headers={"X-User-Id":"user-demo-001"},
    )
    scenarios["idempotent_write"] = client.post(
        "/tools/submit-return-application",
        json={"order_id":"OD202608001", "return_reason":"尺码不合适", "idempotency_key":"skill-eval-write-01"},
        headers={"X-User-Id":"user-demo-001"},
    )

    from apps.api.skills.contracts import SkillExecutionContext, SkillResult
    from apps.api.skills.executor import SkillExecutor

    class Noop:
        class Span:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def set_result(self, *args, **kwargs): pass
        def span(self, *args, **kwargs): return self.Span()

    executor = SkillExecutor(skill_registry, Noop())
    called = {"unauthorized": False, "unconfirmed": False}

    def unauthorized(context, tools):
        result = tools.call("submit_return_application", "write", lambda: called.update(unauthorized=True))
        return SkillResult.from_tool("logistics_inquiry", "logistics", "submit_return_application", result)

    def unconfirmed(context, tools):
        result = tools.call("submit_return_application", "write", lambda: called.update(unconfirmed=True))
        return SkillResult.from_tool("return_resolution", "return", "submit_return_application", result)

    direct = {
        "unauthorized_tool": executor.execute("logistics_inquiry", SkillExecutionContext(trace_id="skill-eval-unauthorized", intent="logistics"), unauthorized),
        "unconfirmed_write": executor.execute("return_resolution", SkillExecutionContext(trace_id="skill-eval-unconfirmed", intent="return"), unconfirmed),
    }

    def trace_skill(response):
        body = response.json()
        trace = client.get(f"/admin/traces/{body['trace_id']}", headers={"X-Role":"supervisor"}).json()
        spans = [span for span in trace["spans"] if span["name"].startswith("skill.")]
        span = spans[-1]
        return {
            "skill_id": span["attributes"]["skill.id"],
            "status": span["attributes"]["skill_status"],
            "tool": span["attributes"].get("tool_name"),
            "error": body.get("error_code"),
            "data": body.get("data") or {},
        }

    observations = {name: trace_skill(response) for name, response in scenarios.items()}
    for name, outcome in direct.items():
        observations[name] = {
            "skill_id": outcome.skill_id, "status": outcome.status,
            "tool": outcome.tool_name, "error": outcome.result.error_code, "data": {},
        }

    results = []
    for case in cases:
        actual = observations[case["scenario"]]
        passed = actual["skill_id"] == case["skill_id"] and actual["status"] == case["expected_status"]
        if case.get("expected_tool"):
            passed = passed and actual["tool"] == case["expected_tool"]
        if case.get("expected_error"):
            passed = passed and actual["error"] == case["expected_error"]
        results.append({"case_id": case["case_id"], "passed": passed, "expected": case, "actual": actual})
    duplicate_write_count = 0 if observations["confirmed_write"]["data"].get("application_id") == observations["idempotent_write"]["data"].get("application_id") else 1
    unauthorized_tool_calls = int(called["unauthorized"])
    unconfirmed_writes = int(called["unconfirmed"])
    passed = sum(item["passed"] for item in results)
    return {
        "total_cases": len(results), "passed_cases": passed,
        "scenario_pass_rate": round(passed / len(results), 4),
        "unauthorized_tool_calls": unauthorized_tool_calls,
        "unconfirmed_writes": unconfirmed_writes,
        "duplicate_writes": duplicate_write_count,
        "failures": [item for item in results if not item["passed"]],
    }


def main() -> None:
    selection = evaluate_selection()
    execution = evaluate_execution()
    passed = (
        selection["selection_accuracy"] >= 0.95
        and selection["high_risk_skill_recall"] == 1.0
        and execution["scenario_pass_rate"] >= 0.95
        and execution["unauthorized_tool_calls"] == 0
        and execution["unconfirmed_writes"] == 0
        and execution["duplicate_writes"] == 0
    )
    report = {
        "report_version": "skill-eval-v1",
        "registry_versions": {skill_id: skill_registry.get(skill_id).version for skill_id in skill_registry.skill_ids},
        "selection": selection,
        "execution": execution,
        "release_gate": {
            "thresholds": {
                "selection_accuracy": 0.95, "high_risk_skill_recall": 1.0,
                "execution_scenario_pass_rate": 0.95, "unauthorized_tool_calls": 0,
                "unconfirmed_writes": 0, "duplicate_writes": 0,
            },
            "passed": passed,
        },
    }
    (ROOT / "evals/skill-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
