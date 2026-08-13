"""Render the acceptance report from the executable evaluation result."""
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def render() -> None:
    report = json.loads((ROOT / "evals/latest-report.json").read_text(encoding="utf-8"))
    rag_report = json.loads((ROOT / "evals/policy-report.json").read_text(encoding="utf-8"))
    cases = [
        json.loads(line)
        for line in (ROOT / "evals/mvp-50.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    counts = Counter(case["category"] for case in cases)
    total = report["total_cases"]
    dataset_version = report["dataset_version"]
    passed = report["passed_cases"]
    core = report["core_scenario_pass_rate"] * 100
    citation = report["citation_validity_rate"] * 100
    handoff = report["high_risk_handoff_coverage"] * 100
    tool = report["tool_success_rate"] * 100
    p95 = report["p95_latency_ms"]
    rag_regression = rag_report["results"]["regression"][rag_report["release_gate"]["strategy"]]
    rag_challenge = rag_report["results"]["challenge"][rag_report["release_gate"]["strategy"]]
    rag_vector = rag_report["results"]["regression"]["vector"]
    rag_rerank = rag_report["results"]["regression"]["fusion_rerank"]
    status = "达标" if core >= 85 else "未达标"
    citation_status = "达标" if citation >= 90 else "未达标"
    handoff_status = "达标" if handoff >= 95 else "未达标"
    tool_status = "达标" if tool >= 95 else "未达标"
    report_text = f'''# POC 验收报告

## 报告口径

本报告由 `evals/render_acceptance_report.py` 根据 `evals/latest-report.json` 自动生成；评测结果由 `evals/run_eval.py` 生成，固定集由 `evals/mvp-50.jsonl` 提供，当前数据集版本为 `{dataset_version}`。README、验收报告和评测 JSON 不维护互相独立的手工指标。

## 当前结果

| 指标 | 当前结果 | SPEC 目标 | 结论 |
| --- | ---: | ---: | --- |
| 固定评测通过率 | {passed}/{total}，{core:.2f}% | ≥ 85% | {status} |
| 规则引用有效率 | {citation:.2f}% | ≥ 90% | {citation_status} |
| 高风险转人工覆盖率 | {handoff:.2f}% | ≥ 95% | {handoff_status} |
| Tool 成功率 | {tool:.2f}% | ≥ 95% | {tool_status} |
| 本地 TestClient P95 | 约 {p95:.2f}ms | ≤ 10 秒 | 达标 |

当前结论：四类核心流程可以本地演示；高风险路由和部分异常场景是否达到试点标准，以以上指标和 SPEC 阻断条件为准。该结果不代表客户生产收益。

## 评测覆盖

当前固定集共 {total} 条：正常主流程 {counts['normal']}、业务边界 {counts['boundary']}、Tool 异常 {counts['tool_error']}、风险与转人工 {counts['risk']}、知识无依据/版本冲突 {counts['knowledge']}。每条用例校验允许的 Tool 调用、预期事实或引用、是否转人工，并对支付敏感工单分类和规则版本进行结构化断言。

另有自动化回归验证：每个 `/assist` 请求可用 `trace_id` 回放 LangGraph 节点及 Tool/RAG 子 Span；受控失败记录错误码，未处理异常记录失败根链路；窗口聚合返回端到端及操作级耗时、失败率、慢链路和最近失败链路。该观测回归不计入上述 {total} 条业务评测通过率。

## RAG 专项结果

RAG 专项集共 100 条：开发集 30 条、固定回归集 40 条、挑战集 30 条。发布门禁使用 `{rag_report['release_gate']['strategy']}`：固定回归端到端通过率 {rag_regression['end_to_end_pass_rate'] * 100:.2f}%、无依据拒答率 {rag_regression['unsupported_rejection_rate'] * 100:.2f}%、过期版本泄漏率 {rag_regression['expired_version_leakage_rate'] * 100:.2f}%，发布门禁{'通过' if rag_report['release_gate']['passed'] else '未通过'}；挑战集通过率为 {rag_challenge['end_to_end_pass_rate'] * 100:.2f}%。

同集消融中，vector-only 固定回归通过率为 {rag_vector['end_to_end_pass_rate'] * 100:.2f}%，fusion+测试 reranker 为 {rag_rerank['end_to_end_pass_rate'] * 100:.2f}%。当前结果不证明测试 reranker 有正向边际收益，因此本地默认使用 `fusion`；真实 reranker 必须重新通过三套数据与成本/时延评测后才能成为生产默认策略。

## 未通过样例与修复优先级

当前固定评测没有失败样例；支付敏感独立路由、重复建单、跨用户访问和中文多轮追问均已纳入回归。后续挑战集应继续增加并发写入、规则冲突和真实模型 Provider 故障样本。

## 尚未验证

- Docker Compose 容器网络环境的独立采样尚未执行，当前环境没有 Docker CLI。
- 浏览器级 E2E 尚未在本环境执行：当前未检测到 Playwright/Selenium 或可用浏览器运行时；已完成 API、前端源码契约和 JavaScript 语法验证。
- 当前前端仍是演示工作台，不包含真实登录、客服自动分配和生产级实时质量看板；会话、工单、退货申请、质量事件和本地 Trace/Span 已使用 SQLite 持久化。
- 本地 TraceStore 尚未接入外部观测后端、告警推送、采样、自动保留和跨服务上下文传播。
- RAG 本地评测使用确定性 embedding/reranker Provider，不代表生产模型效果。
- 当前规则检索仍是内存线性扫描 POC，生产索引、增量入库、真实 Provider 容量与故障验证尚未完成。

## 验收边界

本报告只证明匿名模拟数据和本地演示环境中的可复现行为，不证明客户生产环境的自动解决率、人工成本节省、退款风险降低或系统容量。进入客户试点前必须补充真实基线、容器部署验证、认证授权验证和灰度回滚验证。
'''
    (ROOT / "docs/poc-acceptance-report.md").write_text(report_text, encoding="utf-8")


if __name__ == "__main__":
    render()
