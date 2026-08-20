# API / Tool 契约

## `POST /assist`

统一对话入口由 LangGraph 状态图编排。输入仍使用 `AssistRequest`，响应仍使用统一 Tool 响应结构；增加 Skill 层不改变 HTTP 契约。主意图先映射到 Registry 中的场景 Skill，Skill Executor 再检查触发边界、Tool 权限和写操作确认；订单归属、幂等与业务数据校验继续由 Tool/Service 强制执行。`session_id` 的跨请求上下文由 SQLite `ConversationStore` 持久化并按用户隔离。

`message` 中的表达和结构化请求字段不具有相同权威性：本轮 `order_id`/`return_reason` 高于会话继承状态；显式切换 `order_id` 会使旧订单作用域下的退货原因和已验证事实失效，并重置上一意图与连续未解决计数。过期槽位不会进入路由或 Tool 参数。跨用户复用同一 `session_id` 返回 `403_SESSION_FORBIDDEN`。

意图目录的主意图决定当前路由，次意图用于人工摘要。`complaint` 和 `payment_sensitive` 抢占普通意图；最终节点再次校验主意图是否允许当前 Tool，配置冲突返回 `500_INTENT_TOOL_POLICY_VIOLATION` 且停止自动处理。当前公开响应体不暴露内部槽位或分类分数，目录版本、次意图和风险标签记录在 Trace/人工摘要中，避免把内部策略变成客户端稳定契约。

Skill 运行错误契约：

| 错误码 | 条件 | 是否执行 Tool 回调 |
| --- | --- | --- |
| `500_SKILL_INTENT_POLICY_VIOLATION` | 当前意图不属于目标 Skill 的触发边界 | 否 |
| `500_SKILL_TOOL_POLICY_VIOLATION` | Skill 请求未授权或明确禁止的 Tool | 否 |
| `409_SKILL_CONFIRMATION_REQUIRED` | 需要确认的写 Tool 未收到明确确认 | 否 |

公开响应暂不增加 Skill 字段，避免将内部编排结构固化为客户端契约；主管可通过 Trace 查看 `skill.id/version/phase/status`、调用/拒绝的 Tool 和缺失槽位。

## `POST /tools/query-order-logistics`

查询当前用户有权访问的匿名订单物流状态。MVP 使用 `X-User-Id` 模拟登录身份。

### 请求

```json
{"order_id":"OD202608001"}
```

订单号必须匹配 `^OD\d{9}$`，额外字段会被拒绝。

### 成功响应

```json
{
  "success": true,
  "data": {
    "order_id": "OD202608001",
    "order_status": "运输中",
    "carrier": "Demo Express",
    "latest_event": {
      "occurred_at": "2026-08-12T09:30:00Z",
      "location": "Los Angeles, US",
      "description": "包裹已到达当地分拨中心"
    },
    "exception": false,
    "estimated_arrival": "2026-08-15T18:00:00Z"
  },
  "error_code": null,
    "message": "已查询到最新物流状态。",
  "trace_id": "..."
}
```

### 失败与降级

| HTTP | `error_code` | 行为 |
|---:|---|---|
| 400 | `401_MISSING_USER` | 要求完成身份校验 |
| 403 | `403_ORDER_FORBIDDEN` | 不透露订单详细信息 |
| 404 | `404_ORDER_NOT_FOUND` | 明确无法确认，不生成物流结论 |
| 422 | FastAPI validation error | 拒绝非法订单号 |
| 429 | `429_RATE_LIMITED` | 客户系统限流，可重试 |
| 503 | `503_EXTERNAL_UNAVAILABLE` | 客户系统不可用，转人工 |
| 504 | `504_EXTERNAL_TIMEOUT` | 客户系统超时，转人工 |

所有响应包含 `success`、`data`、`error_code`、`message`、`trace_id`。每个成功 Tool 必须显式提供业务语义明确的 `message`，禁止使用通用“查询成功”作为默认文案。Tool 只返回客户系统响应中映射后的最小必要字段；调用日志记录工具名、trace ID、结果、错误码和耗时。订单/物流数据通过 `CustomerSystemClient` 以 HTTP 访问 Mock Customer Systems（`apps/mock_customer_systems`），并经过 `mappers` 字段映射，不再直接读取本地 JSON。

所有 HTTP 响应同时返回 `X-Trace-Id`；浏览器跨域请求可读取该响应头。服务端生成新的链路号，不接受调用方覆盖本地 Trace。若发生未处理异常，API 返回受控的 `500_INTERNAL_ERROR` 响应和可查询的 `trace_id`。

## `POST /tools/check-return-eligibility`

根据订单状态、签收日期、商品品类和退货原因判断资格。商品质量、损坏、退款争议和投诉默认进入人工审核，不承诺退款。

请求：

```json
{"order_id":"OD202608001","return_reason":"尺码不合适"}
```

成功响应的 `data` 包含 `eligible`、`decision`、`rule_version`、`basis`、`next_steps` 和 `requires_human`。适用规则缺失返回 `424_POLICY_NOT_FOUND`，订单未签收或状态异常返回 `409_ORDER_STATUS_UNSUPPORTED`。

## `POST /tools/search-policy`

检索前硬过滤非 `published`、尚未生效、已经失效或区域不适用的规则。检索候选只有在证据充分性达到 `POLICY_MIN_EVIDENCE_SCORE` 后才能返回成功；否则返回 `404_POLICY_NOT_FOUND`，即使存在主题相关候选也不生成确定性结论。

成功响应的 `citations` 包含 `policy_id/title/version/status/effective_from/effective_to/source/chunk_id/quoted_text`。`quoted_text` 是实际支持答案的片段；只有标题或版本号不构成有效引用。`retrieval` 返回策略、候选数、Provider、证据分数和门禁阈值，供审计与评测使用。

## 人工与质量接口

- `GET /admin/metrics`：需要 `X-Role: supervisor` 或 `X-Role: implementer`（实施管理员内部角色），返回 Tool 错误率、调用数、转人工数和会话数。
- `GET /admin/events`：同样需要实施管理员或主管角色，返回脱敏的会话/Tool 事件及 `trace_id`。
- `GET /admin/traces/{trace_id}`：需要主管或实施管理员角色，返回 HTTP Trace 与按开始时间排列的 LangGraph、模型、RAG、Tool Span；Span 包含父子关系、耗时、状态、错误码和非敏感技术属性。未知链路返回 `404_TRACE_NOT_FOUND`。
- `GET /admin/observability/summary?window_minutes=60`：需要主管或实施管理员角色；窗口范围 1～10080 分钟，返回请求量/失败率、端到端 P50/P95/最大耗时、错误码分布、各操作调用量/失败率/P50/P95、最慢链路、最近失败请求和最近失败 Span。管理查询与健康检查不计入请求汇总。
- `POST /tools/handoff-human`：输入会话摘要、转人工原因和幂等键，输出工单/接管信息；该 Tool 的响应 `handoff` 固定为 `true`。
- `POST /tools/submit-return-application`：这是前端确认动作对应的现有 HTTP 契约，内部以 `confirmed=true` 执行 `return_resolution` 的 `confirm_submit` 阶段；返回申请单号、`待审核` 状态和后续步骤，不代表退款已完成，并继续校验订单归属与幂等键。
- `GET /agent/return-applications`：需要员工身份和 `X-Role: agent`、`supervisor` 或 `implementer`；支持 `page`、`page_size`、`keyword`、`status` 分页筛选，返回退货申请列表和 `pagination`。
- `GET /agent/tickets`：需要员工身份和客服、主管或实施管理员角色；支持 `page`、`page_size`、`keyword`、`status`、`category` 分页筛选，返回人工接管工单列表和 `pagination`。
- `POST /agent/tickets/{ticket_id}/resolve`：需要人工客服或主管；输入处理状态（已解决/待补充信息/已升级主管）和客服回复，保存处理结果；已处理工单不可重复更新。
- `GET /tools/tickets/{ticket_id}`：消费者携带 `X-User-Id` 查询本人转人工工单的最新状态和客服回复；订单/用户不匹配时拒绝访问。
- `POST /agent/return-applications/{application_id}/review`：需要 `X-Role: agent` 或 `supervisor`；输入 `decision=approved|rejected` 和可选原因。驳回时原因必填，成功后状态变为 `审核通过` 或 `审核不通过`，重复审核返回冲突错误。
- `GET /tools/return-applications/{application_id}`：消费者携带 `X-User-Id` 查询本人申请的最新状态；校验订单归属，返回申请状态、审核原因和后续步骤。
- `/assist` 可选接收 `session_id`；未提供时使用当前 `trace_id`，用于关联连续会话事件。
- Tool 失败响应的 `handoff` 为 `true`，表示不得继续生成确定性业务结论。
