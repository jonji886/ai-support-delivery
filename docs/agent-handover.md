# Agent Handover — 未完成任务交接

> 本文档用于把当前会话**未完成的任务**交接给后续 Agent（或人类开发者）。
> 接手前请先阅读：`SPEC.md`、`AGENTS.md`、`README.md`、`docs/architecture.md`（如存在）。
> 交接时间：2026-08-20。

---

## 1. 项目一句话概览

跨境电商售后客服 POC（模拟企业 AI Agent 交付过程）：`Agent → Skill → Tool → Integration Adapter`，FastAPI + LangGraph 后端、React + Vite 前端、Mock OMS/Logistics 客户系统、确定性评测 + 真实 GLM 模型评测、Playwright E2E。

关键路径：

- 后端入口：`apps/api/main.py`（`/assist`、`/tools/*`）
- 编排图：`apps/api/agent/graph.py`
- 前端：`apps/web/src/pages/ChatPage.tsx`
- Mock 客户系统：`apps/mock_customer_systems/`
- 评测：`evals/`（确定性）+ `evals/model_eval.py`（真实 GLM）
- E2E：`apps/web/e2e/support-flow.spec.ts`、`scripts/run_e2e_local.sh`

---

## 2. 已完成工作快照（供接手者建立上下文）

以下工作已全部完成并验证，**不需要重做**，仅作为上下文：

| 项 | 状态 | 验证结果 |
|---|---|---|
| E2E 三个场景（物流查询 / 退货确认 / 投诉转人工） | 完成 | `bash scripts/run_e2e_local.sh` 两侧均 `3 passed`（约 16s） |
| 后端单元/集成测试 | 完成 | `make test`：`172 passed, 2 skipped` |
| 确定性评测 | 完成 | `make eval`：release_gate passed，0 failures |
| 真实 GLM 评测 | 完成 | `evals/model-report.json`：`glm-4-flash`，13/13，accuracy=1.0，high_risk_recall=1.0，call_failures=0 |

本次会话修复过的核心链路（改坏前请理解再动）：

- **消息中提取订单号**：`apps/api/agent/graph.py` 新增 `_extract_order_id`（正则 `\bOD\d{9}\b`），`load_context` 中 `explicit_order_id = request.order_id or _extract_order_id(request.message)`。E2E 直接输入消息也能识别订单。
- **HITL 写操作确认语义（重要，勿改回 409）**：退货资格判断是只读操作，`/assist` 返回 `200` 并在 `data.pending_action` 携带确认信息（含 `eligibility`）；前端 `ChatPage.tsx` 据此弹确认框。未确认的**写操作**（`/tools/*` executor 层）才返回 `409 SKILL_CONFIRMATION_REQUIRED`。当初曾误把资格判断改为 409，会导致 `return-eligibility-success` eval 期望 200 失败，已回退。
- **`next_actions` 传递**：`_SkillOutcome` 增加 `next_actions: list[str]`，状态更新时写入；`/assist` 据此组装 `pending_action`。
- **前端展示契约**：`/assist` 的 `data` 中新增 `tool_results / answer / extracted_state / pending_action` 字段（后端此前根本没有这些字段，前端引用会拿到 undefined）。
- **Mock 数据时态**：`data/mock/orders.json`、`data/mock/customer/oms.json` 的 `signed_at` 已从 `2026-08-05T09:30:00Z` 改为 `2026-08-10T09:30:00Z`（否则第 15 天超过 14 天退货窗口，资格判断永不 eligible）。
- **E2E 场景 2 数据修正**：退货订单用 `ORDER_1 = OD202608001`（归属 user-demo-001），原因用"尺码不合适"（非高危）；"损坏"等高危原因会走 human_review 不走确认框。
- **GLM prompt 陷阱修复**：`evals/model_eval.py` 的 SYSTEM_PROMPT 弃用竖线枚举写法（GLM 会整串返回），改为分点定义 6 个意图 + 边界指引；accuracy 从 0.23 提到 1.0。

---

## 3. 未完成任务清单（后续 Agent 的工作）

### T1（最关键）：修复 `evals/render_acceptance_report.py` 中过期的静态描述

- **位置**：`evals/render_acceptance_report.py` 报告模板中 "## 尚未验证" → "### Automated but not executed（脚本/代码已就绪，尚未实际运行）" 一节（渲染产物对应 `docs/poc-acceptance-report.md` 第 154 行）。
- **问题**：该行是**静态文本**，写着：
  > Model Quality Eval（`evals/model_eval.py`）：真实 GLM 意图分类评测已实现；本环境未配置 `GLM_API_KEY`，运行输出 SKIP 报告并以退出码 0 结束，不伪造模型结果。配置 Key 后执行 `make model-eval` 即可生成真实结果。

  但事实上 `evals/model-report.json` 已生成且 `skipped: false`（GLM-4-flash，13/13，accuracy=1.0），真实评测**已经执行成功**。静态描述与真实状态矛盾。
- **修复方向**：把该行改为**动态渲染**，复用 render 函数开头已有的 `model_report` 加载逻辑（第 17-18 行，`model_report = json.loads(...) if model_report_path.exists() else None`，第 50-74 行已有 `model_section` 的三分支：None / skipped / 真实结果）。建议：
  - 若 `model_report` 为 `None`：保留"未运行"描述。
  - 若 `model_report.get("skipped")`：保留 SKIP 描述。
  - 否则：**不把 Model Quality Eval 列在 "Automated but not executed" 下**，改为在 "### Verified" 一节动态追加"Model Quality Eval 已执行（GLM-4-flash，13/13，100%），结果见 Model Quality 专项结果"，或在 "Automated but not executed" 中改为"已执行"的表述。二选一即可，关键是**不再声称"未配置 GLM_API_KEY"**。
- **验收**：重新运行 `python3 evals/render_acceptance_report.py`，确认生成的 `docs/poc-acceptance-report.md` 中"尚未验证"部分不再出现"本环境未配置 GLM_API_KEY"；Model Quality 状态与 `model-report.json` 一致。

### T2：重新生成 POC 验收报告

- 运行 `python3 evals/render_acceptance_report.py`（或 `make eval` 的最后一步）。
- 检查 `docs/poc-acceptance-report.md` 的 diff 符合 T1 预期。
- 注意：该文件是**脚本生成的产物**，不要手工编辑其中的动态段落（会被覆盖）。

### T3：同步 README 中 Model Quality 描述

- **位置**：`README.md` 第 232 行（评测结果表 "Model Quality（真实模型）" 行）和第 329 行（已知限制 "LLM 评测" 行）。
- **当前**：两者均写"无 `GLM_API_KEY` 时 SKIP，不阻塞 CI"。
- **建议**：既然已跑出真实结果（GLM-4-flash 13/13 100%），可在表格中补充真实结果（如"13/13，100%（GLM-4-flash）"），并保留"无 Key 时 SKIP、不阻塞 CI"的机制说明；限制表可保留或补充"本地已用真实 GLM 采样，无线上流量泛化结论"。
- **验收**：README 与 `docs/poc-acceptance-report.md`、`evals/model-report.json` 口径一致。

### T4：`.gitignore` 补充 E2E 产物目录

- **问题**：`apps/web/playwright-report/` 与 `apps/web/test-results/` 是 Playwright 运行产物，当前在 git status 中显示为 untracked，但根 `.gitignore` 未覆盖。
- **动作**：在根 `.gitignore` 追加：
  ```gitignore
  # Playwright E2E 产物
  apps/web/playwright-report/
  apps/web/test-results/
  ```
- **验收**：`git status` 不再出现这两个目录。

### T5：提交待办（需要用户明确授权）

- **现状**：16 个已修改文件 + 多个 untracked 文件均未提交（`apps/api/agent/graph.py`、`apps/api/main.py`、`apps/web/*`、`tests/*`、`evals/model_eval.py`、`evals/model-report.json`、`apps/web/e2e/`、`apps/web/playwright.config.ts`、`docs/case-study.md`、`scripts/run_e2e_local.sh` 等）。
- **建议顺序**：先完成 T1-T3（报告与 README 还会变更），T4 补齐 gitignore，最后再一次性提交。
- **注意**：根据 AGENTS.md，提交动作需用户明确要求，不要擅自 `git commit`。

---

## 4. 验证命令速查

```bash
make lint              # ruff + 前端 tsc
make test              # 后端 pytest（当前 172 passed, 2 skipped）
make eval              # 全部确定性评测 + model_eval + 渲染验收报告
make model-eval        # 仅真实 GLM 评测（需 GLM_API_KEY，缺 key 时 SKIP 且退出码 0）
bash scripts/run_e2e_local.sh          # 本地 E2E（自动起 Mock+API+Vite）
BASE_URL=<domain> bash scripts/run_e2e_local.sh   # 远程 E2E
cd apps/web && npm run build           # 前端构建
```

E2E 说明：`apps/web/playwright.config.ts` 使用 `channel: "chrome"`（macOS 13 无法下载 Playwright 自带 chromium，CI 同样可用系统 Chrome）。场景 3 的 403 trace 是跨用户负向断言（预期行为）。

---

## 5. 已知注意事项 / 坑（勿踩）

1. **HITL 语义**：资格判断 = 只读 → `200 + pending_action`；写操作未确认 → executor 层 `409 SKILL_CONFIRMATION_REQUIRED`。不要试图把 `/assist` 的资格判断改成 409。
2. **订单归属**：`user-demo-001` ↔ `OD202608001`；`user-demo-002` ↔ `OD202608002`。跨用户查询返回 403（负向测试依赖此行为）。
3. **退货窗口**：14 天（按 `signed_at`）；高危原因（含"损坏"）→ `human_review`，不产生确认框。
4. **时态数据**：mock 数据的 `signed_at` 必须保持在 14 天窗口内，改时间要同步 `tests/test_customer_integration_contract.py` 的断言。
5. **GLM 评测**：`evals/model_eval.py` 需要 `GLM_API_KEY`；未配置时输出 SKIP 报告并以退出码 0 结束（不阻塞 CI，也不伪造结果）。依赖真实网络调用，时延敏感（当前 P95 ≈ 4.8s）。
6. **报告口径**：Model Quality Eval 不计入"268 条确定性检查"合计，是独立专项（`docs/poc-acceptance-report.md` 已有此口径说明）。
7. **文档同步门禁**（AGENTS.md §3.1）：任何改变用户可见行为 / API / 状态流转的改动，必须同步 `SPEC.md`、设计文档、README、测试统计，并在最终回复中列出实际同步的文件。

---

## 6. 推荐接手路径

1. 读完本文件 + `SPEC.md` + `README.md`。
2. 先做 T1（改 render 脚本动态渲染）→ T2（重新渲染报告）→ T3（README 同步）→ T4（gitignore）。
3. 运行 `make lint && make test && make eval` 确认无回归。
4. 若改了前端或 E2E，运行 `bash scripts/run_e2e_local.sh` 回归 E2E。
5. T5 提交前与用户确认。
