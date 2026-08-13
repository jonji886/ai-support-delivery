# API / Tool 契约

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

所有响应包含 `success`、`data`、`error_code`、`message`、`trace_id`。每个成功 Tool 必须显式提供业务语义明确的 `message`，禁止使用通用“查询成功”作为默认文案。Tool 只返回模拟数据中的最小必要字段；调用日志记录工具名、trace ID、结果、错误码和耗时。

## `POST /tools/check-return-eligibility`

根据订单状态、签收日期、商品品类和退货原因判断资格。商品质量、损坏、退款争议和投诉默认进入人工审核，不承诺退款。

请求：

```json
{"order_id":"OD202608001","return_reason":"尺码不合适"}
```

成功响应的 `data` 包含 `eligible`、`decision`、`rule_version`、`basis`、`next_steps` 和 `requires_human`。适用规则缺失返回 `424_POLICY_NOT_FOUND`，订单未签收或状态异常返回 `409_ORDER_STATUS_UNSUPPORTED`。

## 人工与质量接口

- `GET /admin/metrics`：需要 `X-Role: supervisor` 或 `X-Role: implementer`（实施管理员内部角色），返回 Tool 错误率、调用数、转人工数和会话数。
- `GET /admin/events`：同样需要实施管理员或主管角色，返回脱敏的会话/Tool 事件及 `trace_id`。
- `POST /tools/handoff-human`：输入会话摘要、转人工原因和幂等键，输出工单/接管信息；该 Tool 的响应 `handoff` 固定为 `true`。
- `POST /tools/submit-return-application`：用户明确确认后提交模拟退货申请；返回申请单号、`待审核` 状态和后续步骤，不代表退款已完成；必须校验订单归属并支持幂等键。
- `GET /agent/return-applications`：需要员工身份和 `X-Role: agent`、`supervisor` 或 `implementer`；支持 `page`、`page_size`、`keyword`、`status` 分页筛选，返回退货申请列表和 `pagination`。
- `GET /agent/tickets`：需要员工身份和客服、主管或实施管理员角色；支持 `page`、`page_size`、`keyword`、`status`、`category` 分页筛选，返回人工接管工单列表和 `pagination`。
- `POST /agent/tickets/{ticket_id}/resolve`：需要人工客服或主管；输入处理状态（已解决/待补充信息/已升级主管）和客服回复，保存处理结果；已处理工单不可重复更新。
- `GET /tools/tickets/{ticket_id}`：消费者携带 `X-User-Id` 查询本人转人工工单的最新状态和客服回复；订单/用户不匹配时拒绝访问。
- `POST /agent/return-applications/{application_id}/review`：需要 `X-Role: agent` 或 `supervisor`；输入 `decision=approved|rejected` 和可选原因。驳回时原因必填，成功后状态变为 `审核通过` 或 `审核不通过`，重复审核返回冲突错误。
- `GET /tools/return-applications/{application_id}`：消费者携带 `X-User-Id` 查询本人申请的最新状态；校验订单归属，返回申请状态、审核原因和后续步骤。
- `/assist` 可选接收 `session_id`；未提供时使用当前 `trace_id`，用于关联连续会话事件。
- Tool 失败响应的 `handoff` 为 `true`，表示不得继续生成确定性业务结论。
