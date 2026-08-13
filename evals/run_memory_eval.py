"""Execute deterministic short-term business-state scenarios."""

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.support.conversations import ConversationStore


def main() -> None:
    cases = json.loads((ROOT / "evals/memory-cases.json").read_text(encoding="utf-8"))
    current = [datetime(2026, 8, 13, tzinfo=timezone.utc)]
    with tempfile.TemporaryDirectory(prefix="memory-eval-") as directory:
        store = ConversationStore(
            db_path=str(Path(directory) / "memory.db"), ttl_hours=2, clock=lambda: current[0],
            slot_ttl_minutes={"return_reason": 5, "last_intent": 5, "verified_logistics": 3},
        )
        store.save(
            "session-1", user_id="user-1", order_id="OD202608001", intent="return", resolved=False,
            return_reason="尺码不合适", slot_sources={"order_id": "user_explicit", "return_reason": "user_explicit"},
            verified_facts={"logistics": {"order_status": "运输中"}},
        )
        initial = store.get("session-1", "user-1")
        observations = {
            "inherit_order": initial["order_id"],
            "inherit_reason": initial["return_reason"],
            "slot_source:order_id": initial["slots"]["order_id"]["source"],
            "slot_scope:return_reason": initial["slots"]["return_reason"]["scope_order_id"],
            "verified_fact_source": initial["slots"]["verified_logistics"]["source"],
            "cross_user_isolation": store.get("session-1", "user-2") is None,
        }
        store.save(
            "session-1", user_id="user-1", order_id="OD202608009", intent="logistics", resolved=True,
            slot_sources={"order_id": "user_correction"},
        )
        corrected = store.get("session-1", "user-1")
        observations.update({
            "order_correction": corrected["order_id"],
            "correction_clears_reason": corrected["return_reason"],
            "correction_clears_fact": "verified_logistics" in corrected["slots"],
        })
        store.save(
            "session-2", user_id="user-1", order_id="OD202608001", intent="return", resolved=True,
            return_reason="尺码不合适", slot_sources={"order_id": "user_explicit", "return_reason": "user_explicit"},
        )
        current[0] += timedelta(minutes=6)
        expired = store.get("session-2", "user-1")
        observations["reason_expiry"] = expired["return_reason"]
        observations["intent_expiry"] = expired["last_intent"]
        current[0] += timedelta(hours=3)
        observations["session_expiry"] = store.get("session-2", "user-1")

    results = []
    for case in cases:
        key = f"{case['scenario']}:{case['slot']}" if case["scenario"] in {"slot_source", "slot_scope"} else case["scenario"]
        actual = observations[key]
        results.append({"case_id": case["case_id"], "passed": actual == case["expected"], "expected": case["expected"], "actual": actual})
    passed = sum(item["passed"] for item in results)
    report = {
        "report_version": "memory-eval-v1",
        "total_cases": len(results),
        "passed_cases": passed,
        "scenario_pass_rate": round(passed / len(results), 4),
        "cross_user_leakage_rate": 0.0 if observations["cross_user_isolation"] else 1.0,
        "stale_slot_usage_rate": 0.0 if observations["reason_expiry"] is None and observations["intent_expiry"] is None else 1.0,
        "order_correction_accuracy": 1.0 if observations["order_correction"] == "OD202608009" and observations["correction_clears_reason"] is None and not observations["correction_clears_fact"] else 0.0,
        "failures": [item for item in results if not item["passed"]],
    }
    report["release_gate"] = {
        "thresholds": {"scenario_pass_rate": 1.0, "cross_user_leakage_rate": 0.0, "stale_slot_usage_rate": 0.0, "order_correction_accuracy": 1.0},
        "passed": passed == len(results) and report["cross_user_leakage_rate"] == 0 and report["stale_slot_usage_rate"] == 0 and report["order_correction_accuracy"] == 1,
    }
    (ROOT / "evals/memory-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["release_gate"]["passed"] else 1)


if __name__ == "__main__":
    main()
