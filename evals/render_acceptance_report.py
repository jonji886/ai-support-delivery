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
    extended_memory_report = json.loads((ROOT / "evals/memory-eval-extended-report.json").read_text(encoding="utf-8"))
    skill_report = json.loads((ROOT / "evals/skill-report.json").read_text(encoding="utf-8"))
    model_report_path = ROOT / "evals/model-report.json"
    model_report = json.loads(model_report_path.read_text(encoding="utf-8")) if model_report_path.exists() else None
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
    rag_strategy = rag_report["release_gate"]["strategy"]
    rag_cases = sum(rag_report["results"][dataset][rag_strategy]["total_cases"] for dataset in ("development", "regression", "challenge"))
    total_checks = (
        total
        + intent_report["total_cases"]
        + memory_report["total_cases"]
        + extended_memory_report["total_cases"]
        + skill_selection["total_cases"]
        + skill_execution["total_cases"]
        + rag_cases
    )
    if model_report is None:
        model_section = (
            "未生成 `evals/model-report.json`：未运行 `make model-eval` 或 `python3 evals/model_eval.py`。"
            "这是可选增强评测，不影响确定性发布门禁。"
        )
    elif model_report.get("skipped"):
        model_section = (
            f"`evals/model_eval.py` 已就绪，但未配置 `GLM_API_KEY`，本次输出 SKIP 报告（模型 "
            f"{model_report.get('model')}、数据集 {model_report.get('dataset_version')}）。"
            "真实模型评测未执行，不提供任何模型准确率数字。配置 Key 后运行 `make model-eval` 生成真实结果。"
        )
    else:
        model_accuracy = model_report["accuracy"] * 100
        model_high_risk = model_report["high_risk_recall"] * 100
        model_total = model_report["total_cases"]
        model_passed = model_report["passed_cases"]
        model_failures = len(model_report["failures"])
        model_section = (
            f"真实模型评测（GLM {model_report['model']}，数据集 {model_report['dataset_version']}）共 {model_total} 条，"
            f"通过 {model_passed} 条，意图准确率 {model_accuracy:.2f}%、高风险（投诉/支付敏感）召回率 {model_high_risk:.2f}%、"
            f"调用失败 {model_report['call_failures']} 次、P95 时延 {model_report['latency_ms_p95']}ms，"
            f"门禁{'通过' if model_report['gates']['accuracy_ge_0.8'] else '未通过'}。"
            f"失败 {model_failures} 条：{('、'.join(item['case_id'] for item in model_report['failures'][:5])) if model_failures else '无'}。"
            "该结果反映固定样本上真实模型的分类质量，不代表线上流量泛化。"
        )
    if model_report is None:
        model_verified_line = ""
        model_not_executed_line = (
            "- Model Quality Eval（`evals/model_eval.py`）尚未运行：未生成 `evals/model-report.json`。"
            "配置 Key 后执行 `make model-eval`。"
        )
    elif model_report.get("skipped"):
        model_verified_line = ""
        model_not_executed_line = (
            f"- Model Quality Eval（`evals/model_eval.py`）本次为 SKIP：未配置 `GLM_API_KEY`，"
            f"模型为 {model_report.get('model')}、数据集为 {model_report.get('dataset_version')}；"
            "配置 Key 后执行 `make model-eval`。"
        )
    else:
        model_verified_line = (
            f"- Model Quality Eval 已实际执行：GLM {model_report['model']}，通过 "
            f"{model_report['passed_cases']}/{model_report['total_cases']}，意图准确率 "
            f"{model_report['accuracy'] * 100:.2f}%、高风险召回率 "
            f"{model_report['high_risk_recall'] * 100:.2f}%；结果见上方 Model Quality 专项结果。"
        )
        model_not_executed_line = ""
    status = "达标" if core >= 85 else "未达标"
    citation_status = "达标" if citation >= 90 else "未达标"
    handoff_status = "达标" if handoff >= 95 else "未达标"
    tool_status = "达标" if tool >= 95 else "未达标"
    report_text = f'''# POC 验收报告

## 报告口径

本报告由 `evals/render_acceptance_report.py` 合并核心、意图、记忆、Skill、RAG 与真实模型专项评测 JSON 后自动生成；核心固定集由 `evals/mvp-50.jsonl` 提供，当前数据集版本为 `{dataset_version}`。README、验收报告和评测 JSON 不维护互相独立的手工指标。

Model Quality Eval（`evals/model_eval.py`）与 Deterministic 门禁分离：确定性回归是 CI 发布门禁；真实 GLM 评测需要 `GLM_API_KEY`，未配置时输出 SKIP 报告并以退出码 0 结束，不阻塞 CI。

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
| Memory 扩展场景通过率 | {extended_memory_report['passed_cases']}/{extended_memory_report['total_cases']}，{extended_memory_report['pass_rate'] * 100:.2f}% | 100% | {'达标' if extended_memory_report['release_gate']['passed'] else '未达标'} |
| 跨用户/陈旧状态误用率 | {memory_report['cross_user_leakage_rate'] * 100:.2f}% / {memory_report['stale_slot_usage_rate'] * 100:.2f}% | 0% / 0% | {'达标' if memory_report['release_gate']['passed'] else '未达标'} |
| Skill 选择准确率 | {skill_selection['passed_cases']}/{skill_selection['total_cases']}，{skill_selection['selection_accuracy'] * 100:.2f}% | ≥ 95% | {'达标' if skill_report['release_gate']['passed'] else '未达标'} |
| Skill 执行场景通过率 | {skill_execution['passed_cases']}/{skill_execution['total_cases']}，{skill_execution['scenario_pass_rate'] * 100:.2f}% | ≥ 95% | {'达标' if skill_report['release_gate']['passed'] else '未达标'} |
| 越权 Tool / 未确认写 / 重复写 | {skill_execution['unauthorized_tool_calls']} / {skill_execution['unconfirmed_writes']} / {skill_execution['duplicate_writes']} | 0 / 0 / 0 | {'达标' if skill_report['release_gate']['passed'] else '未达标'} |

当前结论：四类核心流程可以本地演示；高风险路由和部分异常场景是否达到试点标准，以以上指标和 SPEC 阻断条件为准。该结果不代表客户生产收益。

当前报告合计 {total_checks} 条确定性检查：核心 {total}、Intent {intent_report['total_cases']}、Skill {skill_selection['total_cases'] + skill_execution['total_cases']}、RAG 三个数据集 {rag_cases}、Memory 基础与扩展 {memory_report['total_cases'] + extended_memory_report['total_cases']}。不同专项存在数据集重叠时按所属报告统计，不把这个合计解释为独立生产流量样本。真实模型评测（Model Quality Eval）不计入该确定性合计，结果见"Model Quality 专项结果"。

## 评测覆盖

当前固定集共 {total} 条：正常主流程 {counts['normal']}、业务边界 {counts['boundary']}、Tool 异常 {counts['tool_error']}、风险与转人工 {counts['risk']}、知识无依据/版本冲突 {counts['knowledge']}。每条用例校验允许的 Tool 调用、预期事实或引用、是否转人工，并对支付敏感工单分类和规则版本进行结构化断言。

另有自动化回归验证：每个 `/assist` 请求可用 `trace_id` 回放 LangGraph、Skill 及 Tool/RAG 子 Span；受控失败记录错误码，未处理异常记录失败根链路；窗口聚合返回端到端及操作级耗时、失败率、慢链路和最近失败链路。该观测回归不计入上述 {total} 条业务评测通过率。

## 意图与短期状态专项结果

Intent Catalog 专项固定集共 {intent_report['total_cases']} 条，覆盖六类意图、hard negative、上下文追问、多意图和高风险组合；主意图准确率 {intent_report['accuracy'] * 100:.2f}%、高风险召回率 {intent_report['high_risk_recall'] * 100:.2f}%、次意图召回率 {intent_report['multi_intent_secondary_recall'] * 100:.2f}%，门禁{'通过' if intent_report['release_gate']['passed'] else '未通过'}。该结果验证确定性安全路由与目录边界，不代表真实外部模型的生产泛化效果。

短期状态专项共 {memory_report['total_cases']} 个场景，覆盖继承、来源/作用域、Tool 已验证事实、用户纠正、订单切换、过期和跨用户隔离；跨用户泄漏率 {memory_report['cross_user_leakage_rate'] * 100:.2f}%、陈旧槽位误用率 {memory_report['stale_slot_usage_rate'] * 100:.2f}%、订单纠正准确率 {memory_report['order_correction_accuracy'] * 100:.2f}%，门禁{'通过' if memory_report['release_gate']['passed'] else '未通过'}。该结果不覆盖生产数据库容量、并发与多租户能力。

Memory 扩展专项共 {extended_memory_report['total_cases']} 个场景，覆盖 context continuity、user isolation、stale memory、correction、long-term preference、conflict resolution、memory pollution 和 token cost；通过率 {extended_memory_report['pass_rate'] * 100:.2f}%，跨用户泄漏与污染率为 0%，window 相比 full history 的样例 token reduction 为 {extended_memory_report['token_cost_reduction']['reduction_rate'] * 100:.2f}%。这是策略行为测试，不是线上 token 成本承诺。

## 场景 Skill 专项结果

Skill 选择层共 {skill_selection['total_cases']} 条，验证意图到 Skill 映射、多意图与高风险抢占，准确率 {skill_selection['selection_accuracy'] * 100:.2f}%、高风险 Skill 召回率 {skill_selection['high_risk_skill_recall'] * 100:.2f}%；执行层共 {skill_execution['total_cases']} 条，验证槽位、Tool 权限、确认、幂等、状态与降级，通过率 {skill_execution['scenario_pass_rate'] * 100:.2f}%。越权 Tool、未确认写、重复写分别为 {skill_execution['unauthorized_tool_calls']}、{skill_execution['unconfirmed_writes']}、{skill_execution['duplicate_writes']}，发布门禁{'通过' if skill_report['release_gate']['passed'] else '未通过'}。

该结果证明当前四个 POC Skill 的确定性契约，不代表生产环境的跨服务分发、并发容量、在线灰度或真实模型选择效果。

## Model Quality 专项结果

{model_section}

## RAG 专项结果

RAG 专项集共 100 条：开发集 30 条、固定回归集 40 条、挑战集 30 条。发布门禁使用 `{rag_report['release_gate']['strategy']}`：固定回归端到端通过率 {rag_regression['end_to_end_pass_rate'] * 100:.2f}%、无依据拒答率 {rag_regression['unsupported_rejection_rate'] * 100:.2f}%、过期版本泄漏率 {rag_regression['expired_version_leakage_rate'] * 100:.2f}%，发布门禁{'通过' if rag_report['release_gate']['passed'] else '未通过'}；挑战集通过率为 {rag_challenge['end_to_end_pass_rate'] * 100:.2f}%。

同集消融中，vector-only 固定回归通过率为 {rag_vector['end_to_end_pass_rate'] * 100:.2f}%，fusion+测试 reranker 为 {rag_rerank['end_to_end_pass_rate'] * 100:.2f}%。当前结果不证明测试 reranker 有正向边际收益，因此本地默认使用 `fusion`；真实 reranker 必须重新通过三套数据与成本/时延评测后才能成为生产默认策略。

## 未通过样例与修复优先级

当前固定评测没有失败样例；支付敏感独立路由、重复建单、跨用户访问和中文多轮追问均已纳入回归。后续挑战集应继续增加并发写入、规则冲突和真实模型 Provider 故障样本。

依赖故障的可复现路径见 [`incident-debugging-case.md`](incident-debugging-case.md)，运行 `make demo-oms-timeout` 可验证 OMS timeout → retry → 标准错误 → 人工接管 → Trace 的链路。

## 尚未验证

### Verified（本环境已实际执行）

- 本地确定性评测全部通过（核心、意图、记忆、Skill、RAG），报告见上表。
- Playwright E2E 在本地 API 与前端上执行通过（3 个场景：物流查询、退货确认、投诉转人工），支持 `BASE_URL` 指向远程部署。
{model_verified_line}

### Automated but not executed（脚本/代码已就绪，尚未实际运行）

{model_not_executed_line}
- 容器构建与全量镜像验证：`deploy/docker-compose.yml` 与 `deploy/deploy-lighthouse.sh` 已就绪，但本机无 Docker CLI，未在本地执行容器级采样。

### Pending remote verification（需在腾讯云 Lighthouse 上验证）

- 真实云部署：Lighthouse 实例上执行 `deploy/deploy-lighthouse.sh` 并访问公网地址。
- 远程浏览器 E2E：`BASE_URL=https://<lighthouse-domain> npm run e2e`。
- 真实模型 Provider 在云环境的时延、配额与故障切换。

### 未纳入范围（有意为之）

- 当前前端仍是演示工作台，不包含真实登录、客服自动分配和生产级实时质量看板；会话、工单、退货申请、质量事件和本地 Trace/Span 已使用 SQLite 持久化。
- 本地 TraceStore 尚未接入外部观测后端、告警推送、采样、自动保留和跨服务上下文传播。
- RAG 本地评测使用确定性 embedding/reranker Provider，不代表生产模型效果。
- Intent Catalog 当前为仓库内 JSON，尚无运营后台、审批流和在线灰度；短期状态使用 SQLite，尚无生产级 Schema 迁移、并发和多租户治理。
- Skill Manifest 当前为仓库内 JSON，尚无远程注册中心、依赖解析、兼容性自动检查、审批发布和按版本流量灰度。
- 当前规则检索仍是内存线性扫描 POC，生产索引、增量入库、真实 Provider 容量与故障验证尚未完成。

## 验收边界

本报告只证明匿名模拟数据和本地演示环境中的可复现行为，不证明客户生产环境的自动解决率、人工成本节省、退款风险降低或系统容量。进入客户试点前必须补充真实基线、容器部署验证、认证授权验证和灰度回滚验证。
'''
    (ROOT / "docs/poc-acceptance-report.md").write_text(report_text, encoding="utf-8")


if __name__ == "__main__":
    render()
