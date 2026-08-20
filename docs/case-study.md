# FDE Delivery Case Study：跨境电商售后 AI 支持 POC

> 本文档以 FDE（Forward Deployed Engineer）交付视角，建立 **Requirement → Decision → Implementation → Evidence** 的完整追踪链。
> 读者可以通过一张表回答："为什么这么做、做了什么、怎么证明它成立"。
> 相关文档：[客户调研](customer-discovery.md) · [方案设计](solution-design.md) · [SPEC](../SPEC.md) · [POC 验收报告](poc-acceptance-report.md)

---

## 1. 交付背景

模拟客户（跨境电商卖家）售后团队需要同时操作 OMS、物流系统、规则库和工单队列。高频率、低错误成本的问题适合自动化；投诉、支付敏感、规则无依据和外部系统故障必须停止猜测并转人工。

这不是"做一个 Chatbot"的项目，而是定义 **什么能自动化、什么必须人工、以及如何证明边界成立** 的交付项目。本 Case Study 只记录本仓库实际实现并验证过的内容；未执行的部分（真实云部署、真实模型评测）单独标注。

## 2. Requirement → Decision → Implementation → Evidence

| # | Requirement（客户诉求） | Decision（技术决策 / ADR） | Implementation（实现位置） | Evidence（验证证据） |
|---|---|---|---|---|
| R1 | 高频物流查询必须自动化，但答案必须来自外部系统事实，不能由模型编造 | 只读查询走 Tool 边界，LLM 只做意图分类；Adapter + Canonical Model 隔离客户系统字段 | [`query_order_logistics` Tool](../apps/api/skills/handlers.py) → [`CustomerSystemClient`](../apps/api/support/customer_client.py) → [`IntegrationAdapter`](../apps/api/support/integration.py) → [`Field Mapper`](../apps/api/support/mappers.py) | 核心回归 58/58；E2E 场景 1；`tests/` 覆盖订单归属校验与失败降级 |
| R2 | 退货判断依赖订单状态、签收时间、规则，且提交申请是写操作 | 资格判断可自动（只读），但写操作必须 HITL 确认 + 幂等键，防止重复提交 | [`check_return_eligibility`](../apps/api/skills/handlers.py) → [`ReturnEligibilityService`](../apps/api/services/return_eligibility.py)；[`submit_return_application`](../apps/api/skills/handlers.py) → [`ReturnApplicationService`](../apps/api/services/return_application.py)；确认与幂等在 [`SkillToolGateway`](../apps/api/skills/executor.py) 强制执行 | Skill eval：未确认写操作被拒、重复提交幂等返回（16/16 选择、13/13 执行）；E2E 场景 2 覆盖确认对话框 |
| R3 | 投诉、退款争议、支付敏感类请求错误成本高，必须停止自动化 | Risk-first routing：高风险意图强制进入人工队列，禁止自动处置 | [`risk_handoff`](../apps/api/agent/graph.py) → [`create_service_ticket`](../apps/api/skills/handlers.py) → [`TicketService`](../apps/api/services/ticket.py)；意图目录见 [ADR-0003](adr/0003-versioned-intent-catalog-and-risk-priority.md) | Intent eval：高风险召回 100%（60/60）；E2E 场景 3 |
| R4 | 外部系统字段名和错误契约不稳定，Skill 不应感知客户命名 | Canonical domain model：客户字段映射发生在 Adapter / Mapper 边界，Skill 只操作 canonical 字段 | [`mappers.py`](../apps/api/support/mappers.py)（`order_no`→`order_id`、`fulfillment_status`→`order_status` 等映射表） | 映射表在 [`data/mock/customer/`](../data/mock/customer/) 驱动下被确定性评测覆盖；[API 契约](api-contracts.md) 文档化 |
| R5 | 外部系统故障时不能猜答案，必须有受控失败路径 | Integration Layer：timeout / retry / circuit breaker + 标准错误码（如 `504_EXTERNAL_TIMEOUT`）；失败转人工 | [`IntegrationAdapter`](../apps/api/support/integration.py) + [`errors.py`](../apps/api/support/errors.py) + 确定性故障注入 | [`incident-debugging-case.md`](incident-debugging-case.md) 可复现 `make demo-oms-timeout`；Trace 记录 `graph → skill → tool` 子 Span |
| R6 | 规则问答必须基于有效证据，不能无依据回答 | 生命周期过滤 + 混合检索 + 证据门禁 + 片段级引用；无证据拒答并转人工 | [`PolicySearchService`](../apps/api/services/policy_search.py) + [`vectorstore/`](../apps/api/support/vectorstore/)（测试用确定性 embedding/reranker） | RAG 回归 40/40；挑战集 76.67%（明确标注为泛化缺口，非 CI 门禁） |
| R7 | 系统需要可观测，能回答"发生了什么、为什么失败、如何追踪" | 每个请求生成 `trace_id`，`graph.* → skill.* → tool.* / rag.*` 分层 Span；SQLite TraceStore / EventStore | [`observability.py`](../apps/api/support/observability.py) + [`events.py`](../apps/api/support/events.py)；admin API 暴露 metrics/traces | Trace 断言在核心回归与 E2E 中验证 |
| R8 | 多轮对话需记住上下文，但不能污染、不能越权 | 结构化短期业务状态 + 多层 Memory（TTL、纠正、隔离、陈旧状态检测），见 [ADR-0004](adr/0004-structured-short-term-business-state.md) | [`memory/`](../apps/api/memory/)（manager/policy/retrieval/store） | Memory 基础 12/12、扩展 9/9；跨用户泄露 / 陈旧状态 / 污染为 0 |
| R9 | 场景编排不能随业务节点膨胀而失控 | LangGraph 只负责状态与路由；Skill 注册表管理场景，Skill Executor 校验意图边界、权限和 Span，见 [ADR-0001](adr/0001-langgraph-controlled-orchestration.md) 与 [ADR-0005](adr/0005-scenario-skills-between-agent-and-tools.md) | [`agent/graph.py`](../apps/api/agent/graph.py)（`REQUIRED_GRAPH_NODES` 拓扑） + [`skills/registry.py`](../apps/api/skills/registry.py) + [`skills/executor.py`](../apps/api/skills/executor.py) | 节点拓扑与边由 `tests/` 固定；Skill 选择 eval 16/16 |
| R10 | 评测结果不能误导为生产准确率 | Deterministic Contract Eval 与 Model Quality Eval 分离；固定回归、挑战集、生产限制三类数据集分层 | [`evals/run_eval.py`](../evals/run_eval.py)（确定性回归）、[`evals/run_intent_eval.py`](../evals/run_intent_eval.py)、[`evals/run_policy_eval.py`](../evals/run_policy_eval.py)、[`evals/model_eval.py`](../evals/model_eval.py)（真实模型，无 Key 时 SKIP） | 报告见 [POC 验收报告](poc-acceptance-report.md)；"100%" 均标注为确定性回归口径 |
| R11 | 交付后客户团队要能独立运维 | 部署、配置、排障、回滚文档化；Docker Compose + Lighthouse 云部署脚本 | [`deploy/docker-compose.yml`](../deploy/docker-compose.yml) + [`deploy/deploy-lighthouse.sh`](../deploy/deploy-lighthouse.sh) + [`docs/deployment-runbook.md`](deployment-runbook.md) | 本地 mock 全链路可跑；真实 Lighthouse 部署状态见 [POC 验收报告](poc-acceptance-report.md)（Verified / Pending） |

## 3. 关键架构决策摘要

| 决策 | 选择 | 替代方案被否原因 |
|---|---|---|
| 编排器 | LangGraph 受控编排（固定拓扑） | 完全 Agent 自主决策 → 无法保证权限与人工接管边界，评测不可复现 |
| 意图路由 | 版本化 Intent Catalog + 风险优先级 | 纯 LLM 自由分类 → 高风险意图漏判代价不可接受 |
| Skill 层 | 场景 Skill（`logistics_inquiry` / `return_resolution` / `policy_qa` / `risk_handoff`） | Agent 直接调 Tool → 写确认、幂等、权限集中在 Skill 边界更可审计 |
| 客户集成 | Adapter + Canonical Model | 直接暴露客户字段 → Skill 与客户系统强耦合 |
| 评测 | Deterministic（CI 门禁）+ Model（真实模型，可选）分离 | 单一"准确率"指标 → 混淆确定性回归与生产泛化能力 |
| 身份 | Mock Auth（`X-User-Id` / `X-Role` 抽象） | 生产 JWT/OAuth → POC 阶段过度设计，边界已抽象便于替换 |

## 4. 数据流（用户 → 业务事实）

```text
用户 / 客服
  → React 工作台（apps/web）
  → FastAPI /assist（apps/api/main.py）
  → LangGraph：load_context → classify_intent → route → skill node → finalize
  → SkillExecutor：allowed_tools / forbidden_tools / 写确认 / 幂等
  → Tool → IntegrationAdapter（timeout / retry / circuit breaker）
  → CustomerSystemClient → Mock OMS / Logistics HTTP API
  ← canonical domain model ← Field Mapper
  → 受控响应 + trace_id + 证据引用 / 人工接管
```

## 5. 本 Case Study 的证据边界

- ✅ **Verified**：本地确定性评测、pytest、前端 build、`make demo-oms-timeout`、Playwright E2E（本地 API）。
- ⏳ **Automated but not executed**：真实 GLM 模型评测（`evals/model_eval.py` 已就绪，无 `GLM_API_KEY` 时 SKIP，不伪造结果）。
- ⏳ **Pending remote verification**：腾讯云 Lighthouse 真实部署（脚本与 Compose 已就绪，需在云端执行验证）。

> 原则：宁可标注"未执行"，也不提交未经真实运行的截图或数字。这是本 Case Study 与"Demo 项目"的关键区别。
