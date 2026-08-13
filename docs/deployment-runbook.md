# 部署与排障 Runbook

## 启动

```bash
docker compose -f deploy/docker-compose.yml up --build
```

API：`http://localhost:8000/health`；演示页：`http://localhost:8080`。

## 配置与日志

当前默认使用本地确定性 Provider 运行演示，不需要外部密钥。数据位于 `data/mock/`，规则位于 `knowledge/`。Tool 日志应关联 `trace_id`、工具名、结果和错误码；不得写入令牌、地址和联系方式。

生产级 RAG 配置要求真实 embedding 服务和 Cross-Encoder/model reranker：

```bash
export RAG_PRODUCTION_MODE=true
export EMBEDDING_API_URL="https://embedding.example.com/v1/embeddings"
export EMBEDDING_API_KEY="..."
export EMBEDDING_MODEL="客户批准的 embedding 模型"
export RERANKER_API_URL="https://reranker.example.com/score"
export RERANKER_API_KEY="..."
export RERANKER_MODEL="客户批准的 Cross-Encoder 模型"
```

检索链路为：文档分块与元数据过滤 → 向量召回 + 关键词召回 → RRF 融合 → Cross-Encoder/model 重排 → 生效日期、区域和版本校验 → 带引用回答。生产环境应为 embedding、索引和 reranker 设置超时、重试、版本和回滚策略。

如需启用 DeepSeek，在启动进程环境中设置 `DEEPSEEK_API_KEY`，或在本地 `.env` 中配置；可用 `DEEPSEEK_ENABLED=false` 强制关闭模型调用。模型请求超时或失败时，系统自动回退到本地意图路由。

## 排障与回滚

- API 健康检查失败：查看 `docker compose logs api`，确认数据文件已复制到镜像。
- 规则无引用：检查 `knowledge/*.json` 的生效版本、区域和关键词。
- 重复建单：检查请求是否复用了相同 `idempotency_key`；MVP 重启会清空内存工单。
- 回滚：切换到最近一次已验收的镜像/代码版本，并在固定评测集上重新验证。
