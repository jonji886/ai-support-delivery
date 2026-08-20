# Customer Discovery

> `Simulated discovery artifact` — 本文不是对真实客户、真实基线或真实 ROI 的陈述。数字均为 `Illustrative`，用于说明 FDE 如何在 POC 前建立假设、范围和验收口径。

## 1. Context

目标客户是一个需要处理跨境电商售后咨询的团队，可能同时使用 OMS、物流查询、规则/知识库和售后工单系统。当前仓库用匿名模拟数据复现这个交付问题，不连接真实客户系统。

## 2. Current Workflow

```text
Customer
   ↓
Support agent
   ├─ OMS：订单状态、签收时间、品类
   ├─ Logistics：承运商、最新节点、预计到达
   ├─ Knowledge base：退换货与物流规则
   └─ Ticket system：投诉、争议、人工审核
```

典型流程是客服先判断用户诉求，再切换系统查询事实或规则；如果是投诉、争议或支付敏感问题，则整理上下文并创建工单。系统间字段命名、错误码和权限校验不应由 Agent 或 Skill 直接承担。

## 3. User Roles

| Role | Need | POC evidence |
|---|---|---|
| Consumer | 快速获得可信答复 | 对话、订单上下文、引用、确认卡片 |
| Support agent | 接管复杂问题并继续处理 | 工单队列、上下文摘要、回复和审核 |
| Supervisor | 判断质量、风险和依赖故障 | Metrics、Trace、失败链路和评测报告 |
| Implementer | 配置接口、规则、评测和交付环境 | Mock systems、Runbook、Acceptance artifact |

## 4. Pain Points

- 简单物流查询频率高，客服需要重复访问多个页面。
- 订单和物流是实时事实，不能由 LLM 根据对话猜测。
- 退货资格同时依赖订单、时间、品类和规则，提交动作又涉及写权限。
- 投诉、退款争议和支付敏感问题的错误成本明显高于少自动化一次。
- 外部系统超时或返回错误时，用户需要可解释的安全兜底，而不是伪造成功。

## 5. Illustrative Business Baseline

以下只是用于 POC 讨论的假设，不是客户数据：

| Metric | Illustrative assumption | Why it matters |
|---|---:|---|
| Monthly support conversations | 10,000 | 估计自动化候选规模 |
| Logistics inquiries | 35% | 高频、只读、事实较明确 |
| Return questions | 25% | 可做资格判断，但写入要确认 |
| Complaints / disputes | 10% | 高错误成本，默认人工 |
| Other | 30% | 首期不承诺自动化 |

这组数字只提供计算框架：`automatable sessions × average handling time` 可以估计潜在节省，但本项目不据此声称 ROI、成本节省或客户收益。

## 6. Candidate AI Scenarios

| Scenario | Why candidate | Initial boundary |
|---|---|---|
| Logistics inquiry | 高频、只读、事实可由 OMS / Logistics 提供 | 归属校验后自动查询；故障转人工 |
| Return eligibility | 规则明确，可分离只读判断与写入 | 资格可判断；提交必须用户确认 |
| Policy Q&A | 规则可版本化并附引用 | 只有有效证据才回答 |
| Complaint / dispute | 需要理解诉求但不适合自主裁决 | 风险识别、摘要、建单、人工处理 |
| Payment-sensitive | 错误成本高、权限敏感 | 不执行普通业务 Tool |

## 7. Automation Decision Matrix

| Scenario | Frequency | Error cost | Data certainty | Decision |
|---|---:|---:|---:|---|
| Logistics inquiry | High | Low | High | Auto read-only |
| Return eligibility | High | Medium | High | Auto decision with evidence |
| Submit return application | Medium | Medium | High | Confirm before write |
| Policy Q&A | Medium | Medium | Depends on evidence | Answer only with citation |
| Complaint / refund dispute | Medium | High | Low / disputed | Human handoff |
| Payment-sensitive request | Low | Critical | — | Never auto-execute |

决策依据是风险和可验证性，不是 Agent 的技术能力。这个矩阵也是后续 Scope、Tool 权限、HITL 和 Evaluation 的输入。

## 8. POC Scope

### In scope

- 四类可演示场景：物流查询、退货资格/申请、规则问答、投诉/异常转人工。
- 独立处理支付敏感高风险子意图：分类、工单和人工接管。
- HTTP Mock OMS / Logistics、Canonical Mapping、受控 Tool、Trace、评测和部署文档。

### Out of scope

- 真实 ERP、物流商、支付、生产工单或客户身份系统。
- 真实个人信息、真实退款、自动退款审批和不可逆高风险写操作。
- 生产级多租户、数据库高可用、在线灰度和真实流量 ROI。

## 9. Success Metrics

POC 验收优先看安全和契约，而不是只看自动化覆盖率：

- 核心固定集通过率 ≥ 85%。
- 高风险意图召回率 100%。
- 规则回答引用有效率 ≥ 90%；无依据问题不得确定性回答。
- Skill 选择与执行通过率 ≥ 95%。
- 越权 Tool、未确认写、重复写均为 0。
- 跨用户泄露、陈旧状态复用和 Memory 污染均为 0。
- 外部依赖失败时返回标准错误、可追踪 Trace 和人工路径。

这些是本地 POC 门禁，不是客户生产 SLA；当前结果见 [`poc-acceptance-report.md`](poc-acceptance-report.md)。

## 10. Key Risks

| Risk | Boundary / mitigation |
|---|---|
| LLM 编造订单或物流事实 | 事实只来自 Tool / Customer System；评测检查返回内容和 Tool 调用 |
| 模型误把投诉路由为普通咨询 | 确定性高风险信号优先；100% high-risk recall gate |
| 未确认写操作 | Skill manifest + Tool Gateway + 409 confirmation + idempotency |
| 客户字段不一致 | Adapter / Mapper / Canonical Model 隔离命名差异 |
| OMS 超时 | timeout → read retry → standard error → safe handoff；见故障案例 |
| POC 指标被误读为生产效果 | 所有数据标记为 Simulated / Illustrative，单独列出限制 |

## 11. Open Questions Before a Real Pilot

- 客户真实会话分布、平均处理时长、转人工率和异常率是多少？
- OMS、物流、工单和知识库的认证方式、限流、SLA、字段字典和版本机制是什么？
- 哪些退货/退款动作允许自动提交，哪些必须人工审批？
- 客户要求的审计字段、数据保留、脱敏和跨境数据边界是什么？
- 是否允许 shadow mode？成功标准是一次解决率、人工耗时、风险漏接率还是其他指标？
- 生产发生依赖故障时，客户希望直接人工接管、排队重试还是暂存请求？

## 12. Discovery → Delivery Handoff

Discovery 输出进入后续交付物：

```text
Discovery assumptions
  → SPEC: scope and acceptance
  → Solution Design: boundaries and data flow
  → Integration contract: fields and errors
  → Evaluation set: business contracts and badcases
  → POC Acceptance: measured local results
  → Runbook / Handoff: operate and troubleshoot
```
