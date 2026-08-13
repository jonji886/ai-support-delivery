"""Run RAG dataset splits and retrieval ablation experiments.

Development cases may guide tuning. Regression cases are the release contract.
Challenge cases estimate generalization and must be rotated after they influence
implementation decisions.
"""

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from apps.api.services.policy_search import PolicySearchService


DATASETS = {
    "development": root / "evals/rag/development.json",
    "regression": root / "evals/rag/regression.json",
    "challenge": root / "evals/rag/challenge.json",
}
STRATEGIES = ("lexical", "vector", "fusion", "fusion_rerank")
DEFAULT_STRATEGY = "fusion"


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile_value + 0.999999) - 1))
    return round(ordered[index], 3)


def evaluate(service: PolicySearchService, cases: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
    supported = [case for case in cases if case["expected_version"] != "none"]
    unsupported = [case for case in cases if case["expected_version"] == "none"]
    recall_hits = retrieval_top1_hits = accepted_answer_hits = rejected_hits = expired_leaks = 0
    latencies: list[float] = []
    failures: list[dict[str, Any]] = []

    for case in cases:
        started = time.perf_counter()
        ranked = service.rank(case["question"], case.get("region", "US"), top_k=5, strategy=strategy)
        result = service.search(case["question"], case.get("region", "US"), "rag-eval", strategy=strategy)
        latencies.append((time.perf_counter() - started) * 1000)
        versions = [item["document"]["version"] for item in ranked]
        forbidden = set(case.get("forbidden_versions", []))
        leaked = bool(forbidden.intersection(versions))
        expired_leaks += int(leaked)

        if case["expected_version"] == "none":
            passed = not result.success
            rejected_hits += int(passed)
        else:
            recall_hits += int(case["expected_version"] in versions)
            retrieval_top1_hits += int(bool(versions) and versions[0] == case["expected_version"])
            cited_version = None
            if result.success:
                citations = (result.data or {}).get("citations", [])
                cited_version = citations[0].get("version") if citations else None
            passed = result.success and cited_version == case["expected_version"] and not leaked
            accepted_answer_hits += int(passed)
        if not passed:
            failures.append({
                "case_id": case["case_id"],
                "category": case["category"],
                "expected_version": case["expected_version"],
                "ranked_versions": versions,
                "accepted": result.success,
                "error_code": result.error_code,
            })

    passed = len(cases) - len(failures)
    return {
        "total_cases": len(cases),
        "supported_cases": len(supported),
        "unsupported_cases": len(unsupported),
        "end_to_end_pass_rate": round(passed / len(cases), 4),
        "recall_at_5": round(recall_hits / len(supported), 4) if supported else 0,
        "retrieval_top1_accuracy": round(retrieval_top1_hits / len(supported), 4) if supported else 0,
        "accepted_answer_accuracy": round(accepted_answer_hits / len(supported), 4) if supported else 0,
        "unsupported_rejection_rate": round(rejected_hits / len(unsupported), 4) if unsupported else 0,
        "expired_version_leakage_rate": round(expired_leaks / len(cases), 4),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 3),
            "p95": percentile(latencies, 0.95),
        },
        "failures": failures,
    }


def main() -> None:
    service = PolicySearchService.from_default_data()
    datasets = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in DATASETS.items()}
    results = {
        dataset_name: {strategy: evaluate(service, cases, strategy) for strategy in STRATEGIES}
        for dataset_name, cases in datasets.items()
    }
    regression = results["regression"][DEFAULT_STRATEGY]
    release_gate = {
        "strategy": DEFAULT_STRATEGY,
        "dataset": "regression",
        "thresholds": {
            "end_to_end_pass_rate": 0.95,
            "unsupported_rejection_rate": 0.90,
            "expired_version_leakage_rate": 0.0,
        },
    }
    release_gate["passed"] = (
        regression["end_to_end_pass_rate"] >= 0.95
        and regression["unsupported_rejection_rate"] >= 0.90
        and regression["expired_version_leakage_rate"] == 0
    )
    report = {
        "report_version": "rag-eval-v2",
        "knowledge_version": "policies-2026-08-p0",
        "index_version": "in-memory-poc-v2",
        "embedding_provider": service.embedding_provider.name,
        "reranker_provider": service.reranker_provider.name,
        "evidence_threshold": service.min_evidence_score,
        "dataset_policy": {
            "development": "允许用于诊断和调参，不用于宣称泛化效果",
            "regression": "稳定发布契约；历史 badcase 修复后进入此集",
            "challenge": "版本验收时运行；一旦用于调参即降级为开发数据并补充新挑战样本",
        },
        "strategies": list(STRATEGIES),
        "results": results,
        "release_gate": release_gate,
    }
    output_path = root / "evals/policy-report.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if release_gate["passed"] else 1)


if __name__ == "__main__":
    main()
