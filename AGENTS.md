# AGENTS.md

> 通用 AI Coding 协作规则。
> 目标：需求清晰、设计合理、实现可靠、验证充分、文档一致。

---

## 1. Core Principles

* **Product First**：先理解问题和用户价值，再写代码。
* **Spec Driven**：需求以 `SPEC.md` 为准。
* **Design Before Code**：复杂功能先设计，再实现。
* **Risk-Based TDD**：核心和高风险逻辑优先测试驱动。
* **Small Changes**：小步修改，避免无关重构。
* **Verify Before Done**：未经验证，不视为完成。
* **Docs as Code**：代码、设计、测试和文档保持一致。
* **No Guessing**：不确定时明确假设，不擅自补充需求。

---

## 2. Source of Truth

文档职责：

* `SPEC.md`：需求、范围、边界、验收标准
* `AGENTS.md`：AI 协作规则
* `docs/architecture.md`：整体技术设计
* `docs/adr/`：重要技术决策
* `plans/`：复杂任务实施计划
* `README.md`：项目价值、使用方式、核心能力

发生冲突时：

```text
SPEC / 明确需求
>
Architecture / ADR
>
Implementation Plan
>
现有代码
```

不要为了适配现有实现而擅自修改需求。

---

## 3. Workflow

默认流程：

```text
Understand
→ Spec
→ Design
→ Plan
→ Implement
→ Test
→ Verify
→ Document
```

### 3.1 文档同步交付门禁

凡是改变用户可见行为、API/Tool、状态流转、权限边界、错误处理或验收口径的代码变更，必须在同一任务内完成以下检查后才能交付：

1. 对照 `SPEC.md` 更新需求范围、边界和验收标准。
2. 对照实现更新相关设计文档、API 契约、ADR 或验收报告；无关文档不做机械修改。
3. 更新 README 中受影响的能力、操作方式、测试命令或已知限制。
4. 更新并验证相关测试集、固定回归用例和测试统计；禁止保留旧数量、旧指标或旧流程描述。
5. 最终回复中明确列出实际同步的文件和验证结果；任一项未完成，必须明确说明未完成原因，不得声称任务已完成。

文档同步不是实现完成后的可选补充，而是 Definition of Done 的组成部分。

### 3.2 前端交互变更门禁

前端 HTML/JavaScript 变更必须额外满足：

1. 修改后提取页面 `<script>` 并执行 JavaScript 语法检查；语法错误时不得启动或交付页面。
2. 禁止把业务数据拼接进内联 `onclick` 等事件属性；使用 `data-*` 属性和事件监听器绑定行为，避免引号、转义和注入问题。
3. 涉及按钮、角色切换、接口请求或状态更新时，至少验证页面加载、目标按钮存在、接口失败提示和核心成功路径。
4. 后端测试通过不代表前端完成；前端脚本、浏览器控制台和关键交互必须单独验证。

开始开发前，优先阅读：

1. `SPEC.md`
2. `AGENTS.md`
3. `README.md`
4. 相关设计文档
5. 相关代码和测试

简单修改无需过度设计；复杂或高风险功能必须先设计和拆解。

---

## 4. Document Creation

仅在任务实际需要时创建文档，避免文档泛滥。

* `SPEC.md` 缺失时，不擅自猜测并生成需求；应以用户明确需求为准。
* 复杂功能或架构变更且 `docs/architecture.md` 不存在时，创建最小必要架构文档。
* 存在重大、长期技术决策时，创建 `docs/adr/<NNN>-<topic>.md`。
* 复杂或多步骤任务且缺少实施计划时，创建 `plans/<NNN>-<topic>.md`。
* 简单修改不要求额外创建 Architecture、ADR 或 Plan。

文档应保持简洁，只记录当前任务真正需要的信息。

---

## 5. Spec & Acceptance

实现前确认：

* 用户和目标
* 核心场景
* 输入和输出
* 功能范围
* 异常和边界
* Out of Scope
* Acceptance Criteria

重要需求应具有可验证的验收标准：

```text
Given
前置条件

When
执行行为

Then
预期结果
```

不得擅自扩大 Scope。

---

## 6. Architecture & Decisions

复杂功能应先确认：

* 模块职责
* 数据流
* API / Tool Contract
* 数据模型
* 权限边界
* 异常处理
* 外部依赖
* 可观测性

优先：

```text
Simple
>
Clear
>
Maintainable
>
Clever
```

重大技术决策使用 ADR 记录：

```text
Context
Options
Decision
Reasons
Trade-offs
```

普通实现细节不需要 ADR。

---

## 7. Implementation Plan

复杂任务编码前拆成可独立验证的小步骤。

每一步应：

* 范围明确
* 完成条件清晰
* 尽量减少跨模块修改
* 可以独立测试或验证

不要一次性生成或重写大量无关代码。

---

## 8. Testing

采用 **Risk-Based TDD**。

优先测试：

* 核心业务逻辑
* 权限与数据隔离
* API / Tool Contract
* 数据转换
* 状态流转
* 安全逻辑
* 异常处理
* Retry / Timeout / Fallback

推荐流程：

```text
Failing Test
→ Minimal Implementation
→ Test Pass
→ Refactor
```

简单 UI、样式和低风险胶水代码不强制 TDD。

测试价值优先于覆盖率数字。

---

## 9. Code Quality

遵循项目已有：

* Formatter
* Linter
* Type System
* Naming Convention
* Directory Structure

代码应：

* 单一职责
* 命名清晰
* 优先复用
* 避免重复
* 避免过早抽象
* 避免隐藏副作用
* 避免无关重构

不要因为个人偏好修改无关代码。

---

## 10. Contracts & Errors

跨模块或外部调用应明确：

```text
Input
Output
Validation
Error
Timeout
Retry
```

重要流程不能只实现 Happy Path。

至少考虑：

* 参数错误
* 权限不足
* 空结果
* 数据不存在
* 外部服务异常
* Timeout
* Rate Limit
* 数据格式错误
* 重试失败

禁止静默吞掉异常。

---

## 11. Security

默认遵循最小权限原则。

重点检查：

* Authentication
* Authorization
* Data Isolation
* Input Validation
* Secret Management
* Sensitive Data
* Injection
* File Upload
* External Tool Access

禁止：

* 硬编码 Secret
* 默认信任用户输入
* 仅依赖 Prompt 实现权限控制
* 在日志中记录敏感信息
* 为解决依赖问题关闭 TLS、签名或完整性校验

---

## 12. Dependency & Mirror Sources

新增依赖前确认：

* 是否真的需要
* 现有能力能否解决
* 是否仍在维护
* 是否引入明显复杂度

在中国大陆网络环境下：

* pip、npm、pnpm、Maven、Gradle、Go、Cargo、Linux 软件源和容器镜像优先使用可信的中国大陆镜像源。
* 镜像不可用、版本滞后或校验失败时回退官方源。
* 镜像配置优先通过环境变量、项目配置或包管理器配置管理，不硬编码到业务代码。
* Docker 镜像加速仅改变下载通道，不替代可信的官方基础镜像。

---

## 13. Observability

核心流程根据需要提供：

* Log
* Metric
* Trace
* Error Reporting

日志应帮助回答：

```text
发生了什么？
发生在哪里？
为什么失败？
如何追踪？
```

避免无意义日志和敏感信息泄露。

---

## 14. Verification

测试通过不代表完成。

提交前按项目实际情况执行：

```text
Lint
Type Check
Unit Test
Integration Test
Build
E2E / Scenario Test
```

并检查：

* 正常路径
* 异常路径
* 边界条件
* 权限
* 外部依赖失败
* Acceptance Criteria

禁止通过删除测试、降低断言、跳过测试或修改需求来制造“测试通过”。

---

## 15. Documentation

代码改变系统行为时，同步受影响的文档。

只更新真正需要更新的内容，例如：

* `README.md`
* `SPEC.md`
* Architecture
* ADR
* API 文档
* Deployment 文档
* CHANGELOG

README 应优先让第一次接触项目的人快速理解：

1. 解决什么问题
2. 为什么值得使用
3. 核心能力
4. Demo / Screenshot
5. 架构或流程
6. Quick Start
7. 已知限制

复杂流程优先使用 Mermaid 等可视化方式表达。

---

## 16. Definition of Done

任务完成前确认：

* [ ] 满足需求
* [ ] 未擅自扩大 Scope
* [ ] Acceptance Criteria 已验证
* [ ] 核心测试通过
* [ ] Lint / Type Check / Build 通过
* [ ] 关键异常路径已验证
* [ ] 无明显安全问题
* [ ] 无遗留调试代码
* [ ] 相关文档已同步
* [ ] 实现与 Architecture / ADR 一致

---

## 17. Agent Behavior

始终：

* 先理解，再修改
* 明确重要假设
* 优先最小可行改动
* 保留现有合理设计
* 主动发现风险和边界问题
* 不隐藏错误
* 不伪造测试结果
* 不声称执行了未实际执行的命令
* 不因追求完整而过度工程化

最终原则：

```text
Understand before coding.
Specify before designing.
Design before complex implementation.
Test what matters.
Verify before declaring done.
Keep code and documentation consistent.
Prefer simple solutions that satisfy the real requirement.
```
