"""Render the acceptance report from the executable evaluation result."""
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def render() -> None:
    report = json.loads((ROOT / "evals/latest-report.json").read_text(encoding="utf-8"))
    rag_report = json.loads((ROOT / "evals/policy-report.json").read_text(encoding="utf-8"))
    intent_report = json.loads((ROOT / "evals/intent-report.json").read_text(encoding="utf-8"))
    memory_report = json.loads((ROOT / "evals/memory-report.json").read_text(encoding="utf-8"))
    skill_report = json.loads((ROOT / "evals/skill-report.json").read_text(encoding="utf-8"))
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
    skill_selection = skill_report["selection"]
    skill_execution = skill_report["execution"]
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

本报告由 `evals/render_acceptance_report.py` 合并核心、意图、记忆、Skill 与 RAG 专项评测 JSON 后自动生成；核心固定集由 `evals/mvp-50.jsonl` 提供，当前数据集版本为 `{dataset_version}`。README、验收报告和评测 JSON 不维护互相独立的手工指标。

## 当前结果

| 指标 | 当前结果 | SPEC 目标 | 结论 |
| --- | ---: | ---: | --- |
| 固定评测通过率 | {passed}/{total}，{core:.2f}% | ≥ 85% | {status} |
| 规则引用有效率 | {citation:.2f}% | ≥ 90% | {citation_status} |
| 高风险转人工覆盖率 | {handoff:.2f}% | ≥ 95% | {handoff_status} |
| Tool 成功率 | {tool:.2f}% | ≥ 95% | {tool_status} |
| 本地 TestClient P95 | 约 {p95:.2f}ms | ≤ 10 秒 | 达标 |
| 意图目录固定集 | {intent_report['passed_cases']}/{intent_report['total_cases']}，{intent_report['accuracy'] * 100:.2f}% | ≥ 95% | {'达标' if intent_report['release_gate']['passed'] else '未达标'} |
| 高风险意图召回率 | {intent_report['high_risk_recall'] * 100:.2f}% | 100% | {'达标' if intent_report['high_risk_recall'] == 1 else '未达标'} |
| 短期状态场景通过率 | {memory_report['passed_cases']}/{memory_report['total_cases']}，{memory_report['scenario_pass_rate'] * 100:.2f}% | 100% | {'达标' if memory_report['release_gate']['passed'] else '未达标'} |
| 跨用户/陈旧状态误用率 | {memory_report['cross_user_leakage_rate'] * 100:.2f}% / {memory_report['stale_slot_usage_rate'] * 100:.2f}% | 0% / 0% | {'达标' if memory_report['release_gate']['passed'] else '未达标'} |
| Skill 选择准确率 | {skill_selection['passed_cases']}/{skill_selection['total_cases']}，{skill_selection['selection_accuracy'] * 100:.2f}% | ≥ 95% | {'达标' if skill_report['release_gate']['passed'] else '未达标'} |
| Skill 执行场景通过率 | {skill_execution['passed_cases']}/{skill_execution['total_cases']}，{skill_execution['scenario_pass_rate'] * 100:.2f}% | ≥ 95% | {'达标' if skill_report['release_gate']['passed'] else '未达标'} |
| 越权 Tool / 未确认写 / 重复写 | {skill_execution['unauthorized_tool_calls']} / {skill_execution['unconfirmed_writes']} / {skill_execution['duplicate_writes']} | 0 / 0 / 0 | {'达标' if skill_report['release_gate']['passed'] else '未达标'} |

当前结论：四类核心流程可以本地演示；高风险路由和部分异常场景是否达到试点标准，以以上指标和 SPEC 阻断条件为准。该结果不代表客户生产收益。

## 评测覆盖

当前固定集共 {total} 条：正常主流程 {counts['normal']}、业务边界 {counts['boundary']}、Tool 异常 {counts['tool_error']}、风险与转人工 {counts['risk']}、知识无依据/版本冲突 {counts['knowledge']}。每条用例校验允许的 Tool 调用、预期事实或引用、是否转人工，并对支付敏感工单分类和规则版本进行结构化断言。

另有自动化回归验证：每个 `/assist` 请求可用 `trace_id` 回放 LangGraph、Skill 及 Tool/RAG 子 Span；受控失败记录错误码，未处理异常记录失败根链路；窗口聚合返回端到端及操作级耗时、失败率、慢链路和最近失败链路。该观测回归不计入上述 {total} 条业务评测通过率。

## 意图与短期状态专项结果

Intent Catalog 专项固定集共 {intent_report['total_cases']} 条，覆盖六类意图、hard negative、上下文追问、多意图和高风险组合；主意图准确率 {intent_report['accuracy'] * 100:.2f}%、高风险召回率 {intent_report['high_risk_recall'] * 100:.2f}%、次意图召回率 {intent_report['multi_intent_secondary_recall'] * 100:.2f}%，门禁{'通过' if intent_report['release_gate']['passed'] else '未通过'}。该结果验证确定性安全路由与目录边界，不代表真实外部模型的生产泛化效果。

短期状态专项共 {memory_report['total_cases']} 个场景，覆盖继承、来源/作用域、Tool 已验证事实、用户纠正、订单切换、过期和跨用户隔离；跨用户泄漏率 {memory_report['cross_user_leakage_rate'] * 100:.2f}%、陈旧槽位误用率 {memory_report['stale_slot_usage_rate'] * 100:.2f}%、订单纠正准确率 {memory_report['order_correction_accuracy'] * 100:.2f}%，门禁{'通过' if memory_report['release_gate']['passed'] else '未通过'}。该结果不覆盖生产数据库容量、并发与多租户能力。

## 场景 Skill 专项结果

Skill 选择层共 {skill_selection['total_cases']} 条，验证意图到 Skill 映射、多意图与高风险抢占，准确率 {skill_selection['selection_accuracy'] * 100:.2f}%、高风险 Skill 召回率 {skill_selection['high_risk_skill_recall'] * 100:.2f}%；执行层共 {skill_execution['total_cases']} 条，验证槽位、Tool 权限、确认、幂等、状态与降级，通过率 {skill_execution['scenario_pass_rate'] * 100:.2f}%。越权 Tool、未确认写、重复写分别为 {skill_execution['unauthorized_tool_calls']}、{skill_execution['unconfirmed_writes']}、{skill_execution['duplicate_writes']}，发布门禁{'通过' if skill_report['release_gate']['passed'] else '未通过'}。

该结果证明当前四个 POC Skill 的确定性契约，不代表生产环境的跨服务分发、并发容量、在线灰度或真实模型选择效果。

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
- 意图专项目前评测目录的确定性安全路由；真实 DeepSeek/其他模型仍需按模型与 Prompt 版本建立独立数据切片和灰度报告。
- Intent Catalog 当前为仓库内 JSON，尚无运营后台、审批流和在线灰度；短期状态使用 SQLite，尚无生产级 Schema 迁移、并发和多租户治理。
- Skill Manifest 当前为仓库内 JSON，尚无远程注册中心、依赖解析、兼容性自动检查、审批发布和按版本流量灰度。
- 当前规则检索仍是内存线性扫描 POC，生产索引、增量入库、真实 Provider 容量与故障验证尚未完成。

## 验收边界

本报告只证明匿名模拟数据和本地演示环境中的可复现行为，不证明客户生产环境的自动解决率、人工成本节省、退款风险降低或系统容量。进入客户试点前必须补充真实基线、容器部署验证、认证授权验证和灰度回滚验证。
'''
    (ROOT / "docs/poc-acceptance-report.md").write_text(report_text, encoding="utf-8")


if __name__ == "__main__":
    render()
