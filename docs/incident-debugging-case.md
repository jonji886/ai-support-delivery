# Incident Debugging Case — Simulated OMS Timeout

> `Simulated FDE incident scenario`：这是用于展示现场排障方法的可复现 POC 故障，不是真实生产事故，也不代表真实客户 SLA 或影响范围。

## Incident

物流查询依赖客户 OMS / Logistics HTTP API。故障注入让客户系统迟迟不返回，验证 Agent 是否会猜测物流状态，还是会经过 timeout、retry、错误映射和人工兜底。

## Symptom

用户询问订单物流后没有得到物流节点，响应包含受控错误码和人工接管信号，而不是一个看似正常的订单状态。

## User Impact

在故障持续期间，物流查询无法自动完成；用户可以看到“暂时无法确认，已转人工”的路径。当前 POC 不会伪造运输状态，也不会把超时请求写成成功。

## Reproduction

```bash
make demo-oms-timeout
```

脚本会：

1. 启动本地 `Simulated` OMS / Logistics HTTP 服务。
2. 启动隔离 SQLite 文件的 API。
3. 设置 `MOCK_CUSTOMER_FAULT=timeout`，由 `CustomerSystemClient` 把故障头转发到 Mock Customer Systems。
4. 调用 `/assist` 的物流查询场景。
5. 打印用户可见响应以及 `/admin/traces/{trace_id}` 的 Span。

也可以手动观察 Mock 客户系统的故障契约：

```bash
curl -i -H 'X-User-Id: user-demo-001' \
  'http://127.0.0.1:8001/oms/orders/OD202608001?fault=timeout'
```

生产环境不应启用 `MOCK_CUSTOMER_FAULT` 或 `MOCK_CUSTOMER_SLOW_MS`。

## Timeline

```text
T0  用户提交物流查询
T1  Agent 选择 logistics_inquiry Skill
T2  Skill 通过 Tool Gateway 调用 query_order_logistics
T3  CustomerSystemClient 请求 OMS，超过 3 秒 deadline
T4  IntegrationAdapter 对只读请求执行一次 retry
T5  第二次仍超时，映射为 504_EXTERNAL_TIMEOUT
T6  Tool 返回 failure + handoff，Graph finalize 记录结果和 trace
T7  客服可用 trace_id 定位失败 Span，并继续人工处理
```

一次请求中的两次失败不会达到默认五次熔断阈值；如果相同 OMS 故障持续发生，`CircuitBreaker` 在连续 5 次失败后进入 `OPEN`，后续请求直接得到 `503_CIRCUIT_OPEN`，等待恢复窗口后进入 `HALF_OPEN`。这一区别避免把“retry”误写成“本次一定触发 circuit breaker”。

## Investigation

排障顺序按交付现场最短路径执行：

1. 先确认用户看到的是失败/人工路径，而不是错误物流事实。
2. 用响应中的 `trace_id` 查询 Trace，确认请求是否进入 `logistics_inquiry` 和 `query_order_logistics`。
3. 区分 `504_EXTERNAL_TIMEOUT`、`503_CIRCUIT_OPEN`、`503_EXTERNAL_UNAVAILABLE` 和订单业务错误。
4. 对照 Mock Customer Systems `/health` 和 fault 配置，判断是依赖不可达、响应慢还是业务数据不存在。
5. 检查 retry 次数、Span duration、最近失败链路和窗口错误率。
6. 故障恢复后先用只读物流查询验证，再恢复相关自动化路径。

## Trace Evidence

脚本输出的 Trace 应至少包含以下可定位证据（具体 `trace_id` 和耗时每次运行不同）：

| Evidence | Expected observation |
|---|---|
| Root trace | route `/assist`，状态为 failure，带 `trace_id` |
| Graph span | `graph.query_logistics` / `graph.finalize` 可回放 |
| Skill span | `skill.logistics_inquiry`，版本和 status 可见 |
| Tool span | `tool.query_order_logistics`，错误码为 timeout 映射结果 |
| Error contract | `504_EXTERNAL_TIMEOUT`，`handoff=true` |
| User response | 不包含猜测的物流状态，说明无法可靠确认并转人工 |

TraceStore 仅用于本地 POC 诊断；它不等于生产级分布式追踪、告警或数据保留方案。

## Root Cause

本次根因是 `Simulated` 客户系统在 timeout fault 模式下超过 `CustomerSystemClient` 的 3 秒 HTTP deadline。Integration Adapter 正确执行只读 retry，但依赖没有在 retry 窗口内恢复，因此进入标准失败契约。不是 LLM 生成了错误物流状态，也不是 Mapper 把有效响应映射错了。

## Temporary Mitigation

- 将物流查询自动化路径临时切换为人工接管。
- 保留 `trace_id`、错误码和依赖系统信息，避免让客服重复猜测根因。
- 故障恢复前不对订单状态、节点或 ETA 做确定性承诺。
- 若仅是短暂抖动，可以保留只读 retry；不要对写操作照搬自动重试。

## Permanent Fix

当前 POC 已具备的控制：

- HTTP timeout 和标准错误映射。
- 只读请求指数退避 retry；写操作不自动 retry，依赖幂等键。
- Circuit breaker：`CLOSED → OPEN → HALF_OPEN`。
- Fault injection、Integration reliability tests 和 Trace。
- 依赖失败时的安全响应和人工路径。

真实客户试点前仍需要：共享熔断状态、客户级限流与告警、依赖 SLA/联系人、故障开关、灰度回滚和生产级事件/队列设计。本 POC 不为此引入 Redis、Kafka 或 Kubernetes。

## Validation

```bash
# 集成可靠性和 HTTP 客户系统契约
.venv/bin/python -m pytest -q tests/test_integration_reliability.py tests/test_customer_integration_contract.py

# 全量发布前验证
make lint
make test
make eval
```

验收重点是：超时不产生 fake success、错误码可解释、需要时转人工、Trace 可回放，且没有把依赖异常平均进“成功率”。

## Customer Communication

对客户/业务方的短消息应只陈述已验证事实：

> 当前物流查询依赖的 OMS 接口在规定时间内没有返回。系统已停止自动判断，没有生成新的物流状态；相关请求已转人工。我们正在用 Trace `{{trace_id}}` 核对依赖恢复情况，恢复后会先验证只读查询，再决定是否恢复自动处理。

这里的 `{{trace_id}}` 是运行时占位符，不是固定示例 ID。

## Lessons Learned

- FDE 排障先把用户影响和安全边界说清楚，再深入依赖组件。
- retry、circuit breaker 和 handoff 是不同控制；每个都要有独立的观测证据。
- “没有答案”比猜测物流事实更可接受；Tool 失败必须阻断事实生成。
- 模拟故障只有在能贯穿客户系统、Adapter、Tool、Skill、Trace 和用户响应时，才构成有用的交付证据。

