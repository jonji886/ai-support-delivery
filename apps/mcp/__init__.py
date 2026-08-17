"""MCP Server — Model Context Protocol 接入层。

只暴露低风险 read-only Tool：
  - query_order_logistics
  - search_policy

核心业务逻辑复用 Service，不复制。
写 Tool 不通过 MCP 暴露。
"""
