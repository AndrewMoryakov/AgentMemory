import unittest

import agentmemory_mcp_server


class AgentMemoryMcpServerTests(unittest.TestCase):
    def test_initialize_returns_supported_protocol_and_server_info(self) -> None:
        response = agentmemory_mcp_server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        self.assertIsNotNone(response)
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(response["result"]["serverInfo"]["name"], "agentmemory")

    def test_tools_list_contains_health_tool(self) -> None:
        response = agentmemory_mcp_server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            }
        )
        self.assertIsNotNone(response)
        tool_names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("memory_health", tool_names)

    def test_unknown_tool_returns_jsonrpc_error(self) -> None:
        response = agentmemory_mcp_server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "missing_tool", "arguments": {}},
            }
        )
        self.assertIsNotNone(response)
        self.assertEqual(response["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
