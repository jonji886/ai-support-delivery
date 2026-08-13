# 部署与排障 Runbook

## 启动

```bash
docker compose -f deploy/docker-compose.yml up --build
```

API：`http://localhost:8000/health`；演示页：`http://localhost:8080`。

运行时依赖包含 `langgraph==0.6.11`。建议在独立虚拟环境或容器中执行 `python3 -m pip install -r requirements.txt`，避免与机器上其他版本的 LangChain/LangSmith 混装。当前未启用 LangGraph checkpointer；会话状态仍由 `CONVERSATION_DB_PATH` 指定的 SQLite 数据库保存，意图资产由 `config/intent-catalog.json` 加载，场景 Skill 由 `config/skills/*.json` 注册，两者均在启动时 fail fast 校验。

## 配置与日志

当前默认使用本地确定性 Provider 运行演示，不需要外部密钥。数据位于 `data/mock/`，规则位于 `knowledge/`。API 默认向标准错误输出单行 JSON 运行日志，并把 Trace/Span 保存到 `runtime/observability.db`；可用 `LOG_LEVEL` 和 `OBSERVABILITY_DB_PATH` 调整。日志关联 `trace_id`、Span、操作、结果、耗时和错误码，但不写入用户原始问题、动态 URL 标识、令牌、地址或联系方式。异常消息默认不持久化；仅可在确认无敏感数据的本地诊断环境临时设置 `OBSERVABILITY_INCLUDE_ERROR_MESSAGES=true`，代码位置栈始终不包含局部变量。

### 用 trace_id 定位失败

先从统一 API 响应体或 `X-Trace-Id` 响应头取得链路号，再查询完整父子链：

```bash
curl -s http://127.0.0.1:8000/admin/traces/<trace_id> \
  -H 'X-Role: supervisor'
```

依次查看 `trace.status/error_type`、状态为 `error` 的 Span、其 `error_code/error_type`，再通过 `parent_span_id` 定位所属 `graph.*` 节点。未处理异常也会返回可查询的 `trace_id`；受控业务失败可能保持 HTTP 200，但对应的 `tool.*` 或 `rag.*` Span 会标记为 `error`。

### 分析耗时和失败

```bash
curl -s 'http://127.0.0.1:8000/admin/observability/summary?window_minutes=60' \
  -H 'X-Role: supervisor'
```

先看 `request_error_rate`、`request_latency_ms.p95` 和 `errors_by_code`，再在 `operations` 中定位高耗时/高失败操作，最后用 `slowest_traces` 或 `recent_failed_traces` 的链路号回放。当前 SQLite 实现适合单实例 MVP；没有自动清理、采样、外部告警和跨服务 Trace，生产部署前应接入集中式观测后端并配置保留周期。

生产级 RAG 配置要求真实 embedding 服务和 Cross-Encoder/model reranker：

```bash
export RAG_PRODUCTION_MODE=true
export EMBEDDING_API_URL="https://embedding.example.com/v1/embeddings"
export EMBEDDING_API_KEY="..."
export EMBEDDING_MODEL="客户批准的 embedding 模型"
export RERANKER_API_URL="https://reranker.example.com/score"
export RERANKER_API_KEY="..."
export RERANKER_MODEL="客户批准的 Cross-Encoder 模型"
export POLICY_MIN_EVIDENCE_SCORE=0.65
export POLICY_MIN_VECTOR_SCORE=0.35
export RAG_RETRIEVAL_STRATEGY=fusion_rerank
```

检索链路为：发布状态/生效窗口/区域硬过滤 → 向量召回 + 关键词召回 → RRF 融合 → 可选 Cross-Encoder/model 重排 → 证据充分性门禁 → 片段级引用回答。本地默认 `fusion`；只有真实 reranker 在开发/回归/新挑战集的消融结果证明收益覆盖延迟和成本后，才设置为 `fusion_rerank`。生产环境还应为 embedding、索引和 reranker 设置超时、重试、版本和回滚策略。

如需启用 DeepSeek，在启动进程环境中设置 `DEEPSEEK_API_KEY`，或在本地 `.env` 中配置；可用 `DEEPSEEK_ENABLED=false` 强制关闭模型调用。模型请求超时或失败时，系统自动回退到本地意图路由。

短期业务状态使用分层 TTL，可通过下列变量调整：

```bash
export CONVERSATION_TTL_HOURS=24
export ORDER_SLOT_TTL_MINUTES=1440
export RETURN_REASON_SLOT_TTL_MINUTES=60
export INTENT_SLOT_TTL_MINUTES=30
export LOGISTICS_FACT_TTL_MINUTES=5
export RETURN_FACT_TTL_MINUTES=15
```

所有值必须是正整数，否则服务启动失败。变更前先判断业务事实的变化速度：延长 TTL 会降低重复询问与 Tool 调用，但增加陈旧状态复用风险；缩短则相反。生产环境修改 Intent Catalog 或 TTL 后，至少执行 `python3 evals/run_intent_eval.py`、`python3 evals/run_memory_eval.py` 和完整固定回归；目录变更还应升级 `version` 并保留发布审批记录。

修改 Skill Manifest 或 Handler 时必须升级语义版本并执行 `python3 evals/run_skill_eval.py`。触发意图、必需槽位、输出或 Tool 权限变化属于契约变更；生产化后应建立 Manifest 审批、兼容性检查、灰度流量和按 Skill 版本回滚。本 POC 尚未实现远程 Skill 市场或动态热加载，配置变更通过应用版本发布。

## 排障与回滚

- API 健康检查失败：查看 `docker compose logs api`，确认数据文件已复制到镜像。
- 规则无引用：检查 `knowledge/*.json` 的生效版本、区域和关键词。
- 意图配置启动失败：检查 `config/intent-catalog.json` 是否包含六个必需意图、owner、正反例，以及各路由必需 Tool 的允许权限。
- 多轮错误复用：检查槽位 `source/scope_order_id/expires_at`，确认用户切换订单时旧订单状态已失效，并运行短期状态专项评测。
- Skill 选错：检查 `graph.classify_intent` 与 `skill.*` Span，确认 Intent Catalog 与 Registry 映射版本，再运行选择层评测。
- Skill 内部失败：检查 `skill.status/missing_slots/called_tools/denied_tools`，再沿父子链查看具体 Tool；不要把受控 `needs_input` 或 `handoff` 当作系统异常。
- 已知 `trace_id` 的失败：调用 `/admin/traces/{trace_id}`，先找错误 Span，再检查其父 LangGraph 节点和错误码。
- P95 升高或错误率异常：调用 `/admin/observability/summary`，按 `operations` 排查模型、RAG 或 Tool，再回放最慢/失败 Trace。
- 重复建单：检查请求是否复用了相同 `idempotency_key`；MVP 重启会清空内存工单。
- 回滚：切换到最近一次已验收的镜像/代码版本，并在固定评测集上重新验证。
