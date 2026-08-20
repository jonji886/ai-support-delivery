# Historical Plan: AI Engineer Portfolio Upgrade

> 历史实施计划，记录 React、Memory、Vector Store、Docker 和评测能力补齐前的目标与 Gap Analysis。该计划中的 P0/P1 实施已完成；当前仓库对外定位以根目录 [`README.md`](../../README.md) 的 Forward Deployed AI / AI Agent Delivery Portfolio 为准。本文件不代表当前 Scope。

> 目标：补齐招聘岗位要求中当前项目缺少的可验证工程证据，不推翻现有架构。

## Current State

已有高价值资产（必须保留）：
- LangGraph 显式状态图（8 节点 + 条件路由）
- Agent / Skill / Tool 三层（Registry → Executor → Gateway → Handler）
- Intent Catalog（6 意图、fail fast、风险优先）
- RAG（lexical/vector/fusion/rerank + evidence gate + citation）
- Tool 权限与写操作确认（白名单 + 409 + 幂等键）
- 人工接管（risk_handoff Skill + 工单 + 审核队列）
- Trace / Observability（SQLite 父子 Span + 指标看板）
- Integration Layer（timeout/retry/circuit breaker/fault injection）
- Eval（58 核心 + 60 意图 + 12 记忆 + 29 Skill + 100 RAG）
- CI（8 个 GitHub Actions job）
- Docker Compose（api + nginx + health check）

## Gap Analysis

| 招聘要求 | 当前 | Gap | 优先级 |
|---|---|---|---|
| React 全栈前端 | 单文件 index.html | 无 React/TS/Vite/组件化 | P0 |
| Memory System | 仅 ConversationStore | 无多策略/Manager/Write Policy/Inspector | P0 |
| Memory Eval | 12 条短期状态 | 无 context continuity/preference/conflict/pollution | P0 |
| Vector DB Provider | 内存 hash | 无 VectorStoreProvider/Chroma | P1 |
| 部署工程化 | api+nginx 挂载 | 无前端构建/.env.example | P1 |
| README 作品集 | 面向 POC 用户 | 非面试官导向 | P1 |
| MCP Server | 无 | 无 MCP | P2 |
| LLM Provider 抽象 | DeepSeekClient 硬编码 | 无 Provider 抽象 | P2 |

## Target

一个技术面试官浏览仓库 3-5 分钟，即可判断：
> 这是独立完成的、具备 React 前端 + FastAPI 后端 + LangGraph Agent + RAG + Memory + Tool Use + 向量检索 + 评测 + 可观测性 + 容器化部署的完整 AI 产品。

## Scope

### P0
1. React + TypeScript + Vite 前端（保留现有视觉信息架构）
2. MemoryManager + 3 种 Memory Strategy
3. Memory Inspector API + UI
4. Memory Eval 扩展

### P1
5. VectorStoreProvider 抽象 + Chroma Provider
6. Docker Compose 升级（web 构建产物 + .env.example）
7. README 重构为作品集导向

### P2（可选）
8. MCP Server（read-only tools）
9. LLMProvider 抽象

## Non-goals

- 不重写 LangGraph / Skill / Tool / RAG 核心逻辑
- 不引入 LangChain / CrewAI / AutoGen
- 不微服务化 / Kubernetes 化
- 不自己部署大模型
- 不伪造云部署 / 生产指标
- 不修改已有评测数据使数字更漂亮

## Architecture (Target)

```
                           ┌────────────────────┐
                           │ React / TypeScript │
                           │     AI Console     │
                           └─────────┬──────────┘
                                     │ REST API
                           ┌─────────▼─────────┐
                           │      FastAPI      │
                           └─────────┬─────────┘
                                     │
                           ┌─────────▼─────────┐
                           │     LangGraph     │
                           │   Agent Runtime   │
                           └──────┬──┬──┬─────┘
                                  │  │  │
                 ┌────────────────┘  │  └─────────────┐
                 ▼                   ▼                ▼
          ┌────────────┐      ┌────────────┐   ┌────────────┐
          │  Memory    │      │    RAG     │   │  Skills    │
          │  Manager   │      │ Retrieval  │   │  / Tools   │
          └─────┬──────┘      └─────┬──────┘   └─────┬──────┘
                │                   │                │
                ▼                   ▼                ▼
          SQLite Store        Chroma / Local      Mock OMS /
                             Vector Store         Ticket APIs
```

## Migration Strategy

### Phase 3: React 前端

目录：
```
apps/web/
├── src/
│   ├── components/      # Chat, TicketList, MetricsPanel, MemoryInspector
│   ├── pages/           # GuidePage, ChatPage, TicketsPage, MetricsPage, RulesPage
│   ├── hooks/           # useChat, useTickets, useMetrics, useMemory
│   ├── services/        # api.ts (fetch wrapper)
│   ├── types/           # API 类型定义
│   ├── styles/          # 共享样式
│   └── App.tsx
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

保留现有页面：
- Consumer: Agent Chat, 订单上下文, AI 回答, 引用展示, Tool 结果, 确认写操作, 人工接管提示
- Agent Operator: 人工接管队列, 会话详情, 回复, 工单状态
- Supervisor: 基础指标, 风险事件, Trace 查询, **Memory Inspector（新增）**

技术选型：React 18 + TypeScript + Vite。不引入复杂状态框架。

### Phase 4: MemoryManager + 多策略 Memory

```
apps/api/memory/
├── __init__.py
├── manager.py           # MemoryManager 统一入口
├── strategies/
│   ├── working.py       # Strategy A: Structured Working Memory (现有 ConversationStore)
│   ├── conversation.py  # Strategy B: Recent Window + Summary
│   └── longterm.py      # Strategy C: Profile + Episodic
├── store.py             # SQLite-backed persistent store
├── policy.py            # Memory Write Policy
└── retrieval.py         # retrieve_relevant_memory()
```

### Phase 5: Memory Inspector + Memory Eval

- API: `GET /admin/memory/{user_id}` — 列出用户所有 Memory
- API: `GET /admin/memory/{user_id}/{memory_type}` — 按类型筛选
- UI: Supervisor 页面新增 Memory Inspector 面板
- Eval: 扩展 `evals/memory-cases.json` + `evals/run_memory_eval.py`

### Phase 6: Chroma Provider

```
apps/api/support/vectorstore/
├── __init__.py
├── base.py              # VectorStoreProvider Protocol
├── local.py             # 确定性内存 provider（测试默认）
└── chroma.py            # Chroma provider（生产/真实运行）
```

配置：`VECTOR_STORE_PROVIDER=local|chroma`

### Phase 7: Docker Compose 升级

- 前端：多阶段构建（node build → nginx serve）
- 新增 `.env.example`
- health check 覆盖 web + api

## Tests

新增测试目录：
```
tests/
├── frontend/            # React 组件测试（Vitest）
├── memory/              # Memory 策略 + 隔离 + 纠正 + 冲突
├── rag/                 # VectorStoreProvider 测试
└── integration/         # 前后端联通
```

已有测试不得因重构失效。

## Acceptance Criteria

### Full Stack
- [ ] React + TypeScript 前端真实运行
- [ ] FastAPI 提供业务 API
- [ ] 前后端实际联通

### Agent
- [ ] LangGraph 保留
- [ ] Skill 保留
- [ ] Tool Use 保留
- [ ] Human-in-the-loop 保留

### Memory
- [ ] Structured Working Memory（保留现有）
- [ ] Conversation Memory（window + summary）
- [ ] Long-term Memory（profile + episodic）
- [ ] Memory Write Policy
- [ ] Retrieval
- [ ] Conflict Resolution
- [ ] TTL（保留现有）
- [ ] User Isolation（保留现有）
- [ ] Memory Inspector
- [ ] Memory Eval（扩展）

### RAG
- [ ] lexical（保留）
- [ ] vector（保留）
- [ ] fusion（保留）
- [ ] citation（保留）
- [ ] refusal（保留）
- [ ] real Vector Store Provider（新增）

### Engineering
- [ ] pytest（保留）
- [ ] frontend build（新增）
- [ ] eval（保留）
- [ ] CI（保留 + 新增 frontend-build job）
- [ ] Docker Compose（升级）
- [ ] health check（保留）
- [ ] persistent storage（保留）
- [ ] structured logging（保留）
- [ ] Trace（保留）

### Portfolio
- [ ] README 前 30 秒可以理解项目
- [ ] 架构图
- [ ] Memory 图
- [ ] Eval 真实数据
- [ ] 已知限制
- [ ] 可复现 Quick Start
