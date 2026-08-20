"""Model Quality Eval — 真实 LLM（GLM）意图分类评测入口。

与确定性回归（run_eval / run_intent_eval / run_skill_eval）分离：

- 确定性回归：固定 Manifest 契约，CI 阻断门禁，不调用任何付费模型。
- Model Quality Eval：真实 GLM 在意图样本上的分类质量与泛化抽样，
  需要 `GLM_API_KEY`；未配置时输出 SKIP 报告并以退出码 0 结束，
  保证 CI 不因未配置密钥而失败，也不伪造任何模型结果。

用法：
    export GLM_API_KEY=...            # 智谱开放平台 API Key
    python3 evals/model_eval.py       # 运行完整评测并写 evals/model-report.json
    python3 evals/model_eval.py --subset 20   # 只跑前 20 条（快速冒烟）

输出：evals/model-report.json（与 render_acceptance_report.py 兼容的字段）。
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("ai_support_delivery.model_eval")

GLM_BASE_URL = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
GLM_MODEL = os.getenv("GLM_MODEL", "glm-4-flash")
GLM_TIMEOUT = float(os.getenv("GLM_TIMEOUT", "8.0"))
VALID_INTENTS = {"logistics", "return", "policy", "complaint", "payment_sensitive", "unknown"}

SYSTEM_PROMPT = (
    "你是售后意图分类器。只输出 JSON："
    '{"intent":"<可选值之一>","confidence":0到1}。\n'
    "intent 只能取其中之一：\n"
    "- logistics：查询订单或包裹的当前状态；\n"
    "- return：申请退货、换货等退换动作；\n"
    "- policy：询问退货、运费、配送时长等规则条款；\n"
    "- complaint：投诉、退款争议、表达不满要求追责；\n"
    "- payment_sensitive：提供或涉及银行卡号、收款账户等敏感支付信息；\n"
    "- unknown：与售后无关的内容。\n"
    "注意：询问规则条文归 policy；提供银行卡或收款账户信息归 payment_sensitive；"
    "单纯表达不满或追责归 complaint；不要输出枚举列表本身。"
)

# 评测集：从确定性 intent-cases.jsonl 抽取固定样本，另含真实模型偏好的泛化表达。
DEFAULT_CASES: list[dict[str, Any]] = [
    {"case_id": "model-logistics-01", "category": "normal", "input": "订单到哪里了", "expected_intent": "logistics"},
    {"case_id": "model-logistics-02", "category": "normal", "input": "帮我查下包裹到哪了", "expected_intent": "logistics"},
    {"case_id": "model-logistics-03", "category": "edge", "input": "那个单号是单号9的快递现在什么状态", "expected_intent": "logistics"},
    {"case_id": "model-return-01", "category": "normal", "input": "我想退货，订单是 OD202608001", "expected_intent": "return"},
    {"case_id": "model-return-02", "category": "edge", "input": "这件衣服穿着不合身能退吗", "expected_intent": "return"},
    {"case_id": "model-policy-01", "category": "normal", "input": "退货运费谁承担", "expected_intent": "policy"},
    {"case_id": "model-policy-02", "category": "edge", "input": "我家这个区域的配送时长规则是什么", "expected_intent": "policy"},
    {"case_id": "model-complaint-01", "category": "normal", "input": "我已经问了三次，一直不退款，我要投诉", "expected_intent": "complaint"},
    {"case_id": "model-complaint-02", "category": "edge", "input": "你们太不负责任了我要找客服投诉到底", "expected_intent": "complaint"},
    {"case_id": "model-payment-01", "category": "normal", "input": "把退款退到我的银行卡上", "expected_intent": "payment_sensitive"},
    {"case_id": "model-payment-02", "category": "edge", "input": "我的收款账户是 6222 开头的卡，钱打这里", "expected_intent": "payment_sensitive"},
    {"case_id": "model-unknown-01", "category": "normal", "input": "今天天气怎么样", "expected_intent": "unknown"},
    {"case_id": "model-unknown-02", "category": "edge", "input": "你们公司楼下有停车位吗", "expected_intent": "unknown"},
]


def _load_local_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:] if line.startswith("export ") else line
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _read_key() -> Optional[str]:
    _load_local_env()
    key = os.getenv("GLM_API_KEY", "").strip()
    return key or None


def classify(client: httpx.Client, message: str) -> Optional[dict[str, Any]]:
    """调用 GLM 意图分类，返回 {intent, confidence}；调用失败返回 None（计入失败，不抛异常）。"""
    payload = {
        "model": GLM_MODEL,
        "temperature": 0,
        "max_tokens": 30,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
    }
    try:
        response = client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('GLM_API_KEY', '')}", "Content-Type": "application/json"},
            json=payload,
            timeout=GLM_TIMEOUT,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        intent = str(parsed.get("intent", "")).strip().lower()
        confidence = float(parsed.get("confidence", 0))
        if intent not in VALID_INTENTS:
            logger.warning("model_eval_invalid_intent: intent=%r", intent)
            return {"intent": "invalid", "confidence": confidence}
        return {"intent": intent, "confidence": confidence}
    except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning(
            "model_eval_call_failed: error_type=%s error=%s", type(exc).__name__, str(exc)[:120]
        )
        return None


def run(cases: list[dict[str, Any]], api_key: str) -> dict[str, Any]:
    started = time.perf_counter()
    latencies: list[float] = []
    results: list[dict[str, Any]] = []
    high_risk_total = high_risk_hits = 0

    with httpx.Client(base_url=GLM_BASE_URL) as client:
        for case in cases:
            call_started = time.perf_counter()
            prediction = classify(client, case["input"])
            latencies.append((time.perf_counter() - call_started) * 1000)
            expected = case["expected_intent"]
            actual = prediction["intent"] if prediction else None
            passed = actual == expected
            if expected in {"complaint", "payment_sensitive"}:
                high_risk_total += 1
                high_risk_hits += int(passed)
            results.append(
                {
                    "case_id": case["case_id"],
                    "category": case.get("category", "normal"),
                    "input": case["input"],
                    "expected_intent": expected,
                    "actual_intent": actual,
                    "passed": passed,
                }
            )

    total = len(results)
    passed = sum(item["passed"] for item in results)
    return {
        "provider": "glm",
        "model": GLM_MODEL,
        "dataset_version": "model-quality-v1",
        "skipped": False,
        "total_cases": total,
        "passed_cases": passed,
        "accuracy": round(passed / total, 4) if total else 0.0,
        "high_risk_total": high_risk_total,
        "high_risk_hits": high_risk_hits,
        "high_risk_recall": round(high_risk_hits / high_risk_total, 4) if high_risk_total else 0.0,
        "call_failures": sum(1 for item in results if item["actual_intent"] is None),
        "latency_ms_p50": round(sorted(latencies)[int(len(latencies) * 0.5)] if latencies else 0, 1),
        "latency_ms_p95": round(sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0, 1),
        "duration_sec": round(time.perf_counter() - started, 2),
        "failures": [item for item in results if not item["passed"]],
        "gates": {
            "accuracy_ge_0.8": round(passed / total, 4) >= 0.8 if total else False,
            "high_risk_recall_ge_1.0": round(high_risk_hits / high_risk_total, 4) >= 1.0 if high_risk_total else False,
        },
    }


def write_report(report: dict[str, Any]) -> Path:
    path = ROOT / "evals" / "model-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="GLM Model Quality Eval")
    parser.add_argument("--subset", type=int, default=0, help="只评测前 N 条用例（0 = 全部）")
    parser.add_argument("--no-write", action="store_true", help="不写 model-report.json")
    args = parser.parse_args()

    api_key = _read_key()
    if not api_key:
        report = {
            "provider": "glm",
            "model": GLM_MODEL,
            "dataset_version": "model-quality-v1",
            "skipped": True,
            "reason": "GLM_API_KEY 未配置；跳过真实模型评测。确定性回归门禁不受影响。",
            "total_cases": 0,
            "passed_cases": 0,
            "accuracy": 0.0,
            "high_risk_total": 0,
            "high_risk_hits": 0,
            "high_risk_recall": 0.0,
            "gates": {"accuracy_ge_0.8": False, "high_risk_recall_ge_1.0": False},
        }
        print("[model_eval] SKIP: GLM_API_KEY 未配置，不运行真实模型评测。")
        if not args.no_write:
            write_report(report)
        return 0

    cases = DEFAULT_CASES
    if args.subset > 0:
        cases = cases[: args.subset]

    print(f"[model_eval] provider=glm model={GLM_MODEL} cases={len(cases)}")
    report = run(cases, api_key)
    print(f"[model_eval] accuracy={report['accuracy']} high_risk_recall={report['high_risk_recall']} failures={len(report['failures'])}")
    for failure in report["failures"]:
        print(f"  FAIL {failure['case_id']}: expected={failure['expected_intent']} actual={failure['actual_intent']}")
    if not args.no_write:
        path = write_report(report)
        print(f"[model_eval] report -> {path}")
    return 0 if report["gates"]["accuracy_ge_0.8"] and report["gates"]["high_risk_recall_ge_1.0"] else 1


if __name__ == "__main__":
    sys.exit(main())
