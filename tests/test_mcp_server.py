"""MCP Server 测试。"""

import pytest

from apps.mcp.server import MCPServer


@pytest.fixture
def server():
    return MCPServer()


class TestMCPServer:

    def test_list_tools_returns_readonly_only(self, server):
        tools = server.list_tools()
        names = {t["name"] for t in tools}
        assert "query_order_logistics" in names
        assert "search_policy" in names
        # 确保没有写 tool
        assert "submit_return_application" not in names
        assert "create_service_ticket" not in names
        assert "handoff_human" not in names

    def test_query_order_logistics(self, server):
        result = server.call_tool("query_order_logistics", {
            "order_id": "OD202608001",
            "user_id": "user-demo-001",
        })
        assert result["success"] is True
        assert result["data"]["order_id"] == "OD202608001"

    def test_query_order_logistics_missing_params(self, server):
        result = server.call_tool("query_order_logistics", {"order_id": "OD202608001"})
        assert result["success"] is False
        assert "required" in result["error"]

    def test_search_policy(self, server):
        result = server.call_tool("search_policy", {
            "question": "7天无理由退货的条件是什么？",
            "region": "US",
        })
        assert result["success"] is True

    def test_search_policy_missing_question(self, server):
        result = server.call_tool("search_policy", {"region": "US"})
        assert result["success"] is False

    def test_unknown_tool(self, server):
        result = server.call_tool("unknown_tool", {})
        assert result["success"] is False
        assert "unknown tool" in result["error"]

    def test_tools_have_input_schema(self, server):
        for tool in server.list_tools():
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"
            assert "properties" in tool["inputSchema"]

    def test_tools_have_description(self, server):
        for tool in server.list_tools():
            assert "description" in tool
            assert len(tool["description"]) > 0
            # read-only 标识
            assert "read-only" in tool["description"].lower()
