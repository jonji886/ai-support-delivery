# Portfolio Walkthrough

> 面试时的 5–10 分钟讲解路径。所有业务数据和指标均为 `Simulated` / `Illustrative` POC 证据。

## 1. Customer Problem

跨境电商售后客服需要在 OMS、物流、规则库和工单队列之间切换。物流查询频率高且事实明确，退货判断有结构化规则；投诉、支付敏感和外部系统故障则不适合让 LLM 自主裁决。

## 2. My Scope

我把项目范围限制在四类可演示场景：物流查询、退货资格/申请、规则问答、投诉/异常转人工，并单独处理支付敏感高风险意图。真实客户系统、真实个人信息、真实 ROI 和生产 SLA 不在 POC 范围内。

## 3. Architecture Decision

保留 `Agent → Skill → Tool` 三层：

- Agent / LangGraph 负责上下文、意图、状态和流程编排。
- Skill 负责场景槽位、Tool 白名单、确认、降级和输出契约。
- Tool / Service 负责原子业务动作、事实、权限、幂等和审计。
- Integration Adapter 负责客户系统的 timeout、retry、circuit breaker 和错误映射。

这样做的原因是：模型可以理解自然语言，但不能拥有订单状态、物流状态或写入权限。

## 4. Integration

Agent 通过 `CustomerSystemClient → IntegrationAdapter → Mapper` 访问模拟 HTTP OMS / Logistics。客户字段如 `order_no`、`fulfillment_status`、`tracking_events` 在 [`apps/api/support/mappers.py`](../apps/api/support/mappers.py) 中转换为 canonical domain model；Skill 不感知客户字段命名。Ticket 在本 POC 中是 SQLite Service，未虚构外部 SCRM 已接入。

## 5. Safety

退货流程把资格判断和提交写入拆开：

```text
check_return_eligibility (read)
  → show decision and next step
  → explicit user confirmation
  → permission + ownership + idempotency
  → submit_return_application (write)
```

投诉、支付敏感、低置信度、无依据知识和依赖故障都会停止普通自动化并进入人工路径。Tool Gateway 和 `finalize` 都会再次校验权限，避免只依赖 Prompt。

## 6. Evaluation

当前 deterministic POC 报告：核心 58/58、Intent 60/60、高风险召回 100%、Skill 选择 16/16、执行 13/13、RAG 回归 100%、RAG Challenge 76.67%、Memory 基础 12/12、扩展 9/9。关键阻断条件是高风险漏接、越权 Tool、未确认写、重复写、跨用户泄露和陈旧状态复用。

这里必须主动说明：固定回归集的 100% 只能说明已知契约没有回归，不等于生产准确率；Challenge 集和真实模型仍需独立评测。

## 7. Failure Case

运行 `make demo-oms-timeout`，让 Mock OMS 超过 HTTP deadline：

```text
OMS timeout
  → read retry
  → 504_EXTERNAL_TIMEOUT
  → no guessed logistics status
  → human handoff
  → trace_id locates graph / skill / tool spans
```

完整排障材料见 [`incident-debugging-case.md`](incident-debugging-case.md)。

## 8. Limitations

当前系统仍是本地 POC：模拟身份、SQLite、单进程熔断、内存 RAG、deterministic provider、无真实云部署、无浏览器级 E2E、无生产级外部 Trace/告警。README 和验收报告都把这些限制列出，不将设计方案写成已完成事实。

## 9. What I Would Do in Production

下一步不是堆叠 Agent，而是围绕客户约束补齐交付条件：

- 客户认证、RBAC、多租户隔离和敏感字段脱敏。
- PostgreSQL、迁移、备份、并发控制和可靠事件流。
- 客户 OMS / Logistics / Ticket 的契约测试、SLA、限流、告警和共享熔断状态。
- OpenTelemetry、采样、保留策略、SLO、灰度和可回滚部署。
- 真实流量 shadow / canary、模型与 Prompt 版本化评测、成本和延迟观测。
- 客户确认后的写操作紧急禁用、人工分配和运行手册演练。

这些是生产化路线，不是本轮为了 Portfolio 新增的基础设施。

