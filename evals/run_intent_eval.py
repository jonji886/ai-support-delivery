"""Evaluate the versioned Intent Catalog and render a confusion matrix."""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.services.intent_catalog import IntentCatalog


def safe_div(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def main() -> None:
    catalog = IntentCatalog.from_default_data()
    cases = [json.loads(line) for line in (ROOT / "evals/intent-cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    labels = sorted(catalog.intents)
    matrix = {expected: {actual: 0 for actual in labels} for expected in labels}
    failures = []
    risk_total = risk_hits = multi_total = secondary_hits = 0

    for case in cases:
        decision = catalog.classify(case["input"], case.get("previous_intent"))
        expected, actual = case["expected_intent"], decision["intent"]
        matrix[expected][actual] += 1
        passed = actual == expected
        if case.get("expected_risk_label"):
            risk_total += 1
            risk_match = case["expected_risk_label"] in decision["risk_labels"]
            risk_hits += int(risk_match)
            passed = passed and risk_match
        if case.get("expected_secondary"):
            multi_total += 1
            secondary_match = case["expected_secondary"] in decision["secondary_intents"]
            secondary_hits += int(secondary_match)
            passed = passed and secondary_match
        if not passed:
            failures.append({"case_id": case["case_id"], "expected": expected, "actual": actual, "decision": decision})

    per_intent = {}
    for label in labels:
        tp = matrix[label][label]
        fp = sum(matrix[expected][label] for expected in labels if expected != label)
        fn = sum(matrix[label][actual] for actual in labels if actual != label)
        precision, recall = safe_div(tp, tp + fp), safe_div(tp, tp + fn)
        per_intent[label] = {
            "precision": precision,
            "recall": recall,
            "f1": safe_div(round(2 * precision * recall, 8), round(precision + recall, 8)),
            "support": sum(matrix[label].values()),
        }
    passed_cases = len(cases) - len(failures)
    report = {
        "report_version": "intent-eval-v1",
        "catalog_version": catalog.version,
        "dataset_version": "intent-cases-v1",
        "total_cases": len(cases),
        "passed_cases": passed_cases,
        "accuracy": safe_div(passed_cases, len(cases)),
        "high_risk_recall": safe_div(risk_hits, risk_total),
        "multi_intent_secondary_recall": safe_div(secondary_hits, multi_total),
        "labels": labels,
        "confusion_matrix": matrix,
        "per_intent": per_intent,
        "failures": failures,
        "release_gate": {
            "thresholds": {"accuracy": 0.95, "high_risk_recall": 1.0, "multi_intent_secondary_recall": 0.90},
            "passed": safe_div(passed_cases, len(cases)) >= 0.95 and safe_div(risk_hits, risk_total) == 1.0 and safe_div(secondary_hits, multi_total) >= 0.90,
        },
    }
    (ROOT / "evals/intent-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["release_gate"]["passed"] else 1)


if __name__ == "__main__":
    main()
