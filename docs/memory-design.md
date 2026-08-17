# Memory System Design

> 为什么 AI Agent 需要 Memory？如何在售后场景中正确使用 Memory？

## Why Memory

LLM 是无状态的。每一次调用，模型只看到当前 Prompt。但售后场景需要：

1. **多轮上下文**：用户说"订单 OD001 到哪了"，下一句"什么时候到"，不需要重复输入订单号。
2. **跨会话偏好**：用户说"以后回答简洁点"，新会话也应记住。
3. **历史事件**：用户上周的人工接管摘要，本周仍可参考。
4. **业务状态**：当前订单号、退货原因、已验证的物流事实。

没有 Memory，Agent 每轮都要重新询问所有信息，体验极差。

## Memory Taxonomy

```
┌─────────────────────────────────────────────────┐
│                Memory System                     │
├─────────────────┬───────────────────────────────┤
│  Working Memory │  当前 Agent 执行的业务状态      │
│  (Strategy A)   │  order_id, return_reason,     │
│                 │  verified_facts, intent, TTL   │
├─────────────────┼───────────────────────────────┤
│  Conversation   │  最近对话窗口 + 摘要           │
│  Memory         │  RecentMessages + Summary     │
│  (Strategy B)   │  window_size, summary_trigger │
├─────────────────┼───────────────────────────────┤
│  Long-term      │  Profile Memory (稳定偏好)     │
│  Memory         │  Episodic Memory (历史事件)   │
│  (Strategy C)   │  跨 session, 跨会话            │
└─────────────────┴───────────────────────────────┘
```

### Memory vs RAG vs Tool

| 维度 | Memory | RAG | Tool |
|---|---|---|---|
| 保存什么 | 用户/会话/历史上下文 | 共享知识库 | 实时业务事实 |
| 例子 | "用户偏好简洁回答" | "7天无理由退货政策" | "订单 OD001 物流状态" |
| 生命周期 | Session/Long-term | 持久 | 实时 |
| 来源 | 对话/推测 | 知识库文档 | 业务系统 API |
| 优先级 | 最低（不能覆盖 Tool） | 中 | 最高（实时事实） |

**关键原则：Memory 不替代 Tool。Tool 返回的实时业务事实永远优先于 Memory 中的历史记录。**

## Ownership

| 信息类型 | 存储位置 | 管理者 |
|---|---|---|
| Agent 执行状态 | LangGraph State | `SupportState` TypedDict |
| 业务状态（order_id 等） | ConversationStore | Working Memory |
| 对话消息 | MemoryStore | Conversation Memory |
| 对话摘要 | MemoryStore | Conversation Memory |
| 用户偏好 | MemoryStore | Long-term Memory (Profile) |
| 历史事件 | MemoryStore | Long-term Memory (Episodic) |
| 政策知识 | 知识库 JSON / VectorStore | RAG |
| 实时物流/订单状态 | OMS API（Mock） | Tool |

## Lifecycle

### Create

```
User Message
   ↓
Memory Candidate Extraction (policy.py)
   ↓
Memory Policy (是否值得保存？)
   ├── 否 → Ignore
   └── 是 ↓
   Conflict Resolution (与旧 Memory 冲突？)
   ├── 用户纠正 → 覆盖
   ├── 已存在相同 → 跳过
   └── 无冲突 → 写入
   ↓
Persist (store.upsert)
```

### Retrieve

```
retrieve_relevant_memory()
   ↓
根据 user_id + session_id + intent + order_id
   ↓
选择有限 Memory:
  - Conversation Window (最近 N 条)
  - Conversation Summary (摘要)
  - Profile (稳定偏好)
  - Episodic (历史事件, 按 order 过滤)
   ↓
Context Builder:
  Current Request
  + Structured Business State
  + Recent Conversation
  + Relevant Long-term Memory
  + Retrieved Knowledge (RAG)
  + Tool Result
```

### Update

- 用户显式纠正 → 覆盖旧值（source = user_correction）
- 偏好相同 → 跳过（不重复写入）
- 模型推测 → 不覆盖用户明确事实

### Expire

- Working Memory: 按 slot TTL（order_id=24h, return_reason=1h, verified_logistics=5min）
- Conversation Memory: 按 session TTL（默认 2h）
- Long-term Memory: 无自动过期（除非显式设置）

### Delete

- `clear_session()`: 清除会话级 Conversation Memory
- `purge_expired()`: 清理过期 Memory
- `deactivate()`: 标记单条 Memory 为 expired

## Conflict Resolution

```
优先级：User Explicit Correction > Existing Memory > Model Inference
```

| 场景 | 旧值来源 | 新值来源 | 决策 |
|---|---|---|---|
| 用户纠正 | user_explicit | user_correction | 覆盖 |
| 用户新偏好 | user_explicit | user_explicit | 覆盖 |
| 模型推测 vs 用户明确 | user_explicit | model_inference | 不覆盖 |
| 值相同 | 任意 | 任意 | 跳过 |
| 无旧值 | — | 任意 | 写入 |

## Privacy / Isolation

- Memory 严格按 `user_id` 隔离
- `get_conversation_window(session_id, user_id)` 同时校验 user_id
- `list_memory(user_id)` 只返回该用户的 Memory
- session 归属检查：`session_belongs_to_other_user()`
- **cross_user_leakage = 0** 是硬性门禁

## Failure Modes

| 失败模式 | 描述 | 防护措施 |
|---|---|---|
| Stale Memory | 订单变化后旧事实继续使用 | 订单切换时清理 order-scoped slots |
| Wrong-user Memory | A 的 Memory 泄露给 B | user_id 隔离 + session 归属检查 |
| Hallucinated Memory | 模型推测写入虚构事实 | 模型推测不覆盖用户明确值 |
| Context Pollution | 无价值闲聊写入长期 Memory | Memory Write Policy 过滤 |
| Unlimited History | 全部聊天历史放入 Prompt | Window + Summary 策略 |
| Summary Distortion | 摘要丢失关键信息 | Summary 仅作语言上下文，不覆盖业务事实 |

## Evaluation

Memory Eval 覆盖 8 个维度：

1. **Context Continuity** — 多轮不重复询问
2. **User Isolation** — cross_user_leakage = 0
3. **Stale Memory** — 订单变化后旧事实不污染
4. **Correction** — 用户纠正后使用新值
5. **Long-term Preference** — 跨 session 偏好生效
6. **Conflict Resolution** — 用户纠正 > 旧 Memory
7. **Memory Pollution** — 闲聊不写入长期 Memory
8. **Token Cost** — window vs full_history 对比

## Implementation

```
apps/api/memory/
├── __init__.py
├── manager.py       # MemoryManager 统一入口
├── store.py         # SQLite-backed persistent store
├── policy.py         # Memory Write Policy
└── retrieval.py     # retrieve_relevant_memory()
```

配置：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_DB_PATH` | `runtime/memory.db` | Memory SQLite 路径 |
| `CONVERSATION_DB_PATH` | `runtime/conversations.db` | Working Memory SQLite 路径 |
| `CONVERSATION_TTL_HOURS` | `24` | 会话过期时间 |
