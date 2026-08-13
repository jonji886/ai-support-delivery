# 使用 LangGraph 编排受控售后工作流

`/assist` 采用 LangGraph 显式状态图替代集中式条件分支，以提升路由可读性、节点级测试能力和后续扩展性；LangGraph 只拥有编排状态，订单、规则、工单和退货申请的事实与写权限仍属于现有业务 Service。当前跨请求会话继续由 SQLite `ConversationStore` 持久化且不启用 LangGraph checkpointer，避免双写；只有未来出现需要暂停和恢复的长事务时，才在明确单一状态所有权后引入持久化 checkpoint。
