"""MCP Server — Model Context Protocol 接入层。

暴露 read-only tools 供 MCP 客户端使用。
核心业务逻辑复用 Service，不复制。

MCP 是另一种 Tool 接入协议，不改变核心业务 Service 的权限边界。
写 Tool（submit_return_application 等）不通过 MCP 暴露。

运行方式：
  python -m apps.mcp.server

或通过 stdio：
  python -m apps.mcp.server --transport stdio
"""

import json
import sys
from typing import Any

from apps.api.services.order_logistics import OrderLogisticsService
from apps.api.services.policy_search import PolicySearchService
from apps.api.support.responses import new_trace_id


class MCPServer:
    """最小 MCP Server — 暴露 read-only tools。"""

    def __init__(self) -> None:
        self.logistics_service = OrderLogisticsService.from_default_data()
        self.policy_service = PolicySearchService.from_default_data()

    def list_tools(self) -> list[dict[str, Any]]:
        """列出可用 tools。"""
        return [
            {
                "name": "query_order_logistics",
                "description": "查询订单物流状态。read-only。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string", "description": "订单号"},
                        "user_id": {"type": "string", "description": "用户 ID"},
                    },
                    "required": ["order_id", "user_id"],
                },
            },
            {
                "name": "search_policy",
                "description": "搜索售后政策知识库。read-only。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "问题"},
                        "region": {"type": "string", "description": "地区", "default": "US"},
                    },
                    "required": ["question"],
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用 tool。"""
        trace_id = new_trace_id()

        if name == "query_order_logistics":
            order_id = arguments.get("order_id", "")
            user_id = arguments.get("user_id", "")
            if not order_id or not user_id:
                return {"success": False, "error": "order_id and user_id are required"}
            result = self.logistics_service.query(order_id, user_id, trace_id)
            return result.model_dump()

        if name == "search_policy":
            question = arguments.get("question", "")
            region = arguments.get("region", "US")
            if not question:
                return {"success": False, "error": "question is required"}
            result = self.policy_service.search(question, region, trace_id)
            return result.model_dump()

        return {"success": False, "error": f"unknown tool: {name}"}


def handle_stdio() -> None:
    """通过 stdio 处理 MCP 请求。"""
    server = MCPServer()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            method = request.get("method", "")

            if method == "tools/list":
                response = {"tools": server.list_tools()}

            elif method == "tools/call":
                tool_name = request.get("params", {}).get("name", "")
                arguments = request.get("params", {}).get("arguments", {})
                response = server.call_tool(tool_name, arguments)

            else:
                response = {"error": f"unknown method: {method}"}

        except Exception as e:
            response = {"error": str(e)}

        print(json.dumps(response, ensure_ascii=False), flush=True)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MCP Server for AI Support Delivery")
    parser.add_argument("--transport", choices=["stdio"], default="stdio", help="Transport type")
    args = parser.parse_args()

    if args.transport == "stdio":
        handle_stdio()
    else:
        print(f"Unsupported transport: {args.transport}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
