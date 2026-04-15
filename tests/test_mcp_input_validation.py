import sys
from unittest.mock import MagicMock

sys.modules.setdefault("mem0", MagicMock())

import unittest

import agentmemory.mcp as agentmemory_mcp
import agentmemory.runtime.operations as agentmemory_operations


class McpInputValidationTests(unittest.TestCase):
    def test_tools_call_rejects_none_name(self) -> None:
        response = agentmemory_mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": None, "arguments": {}},
            }
        )
        self.assertIsNotNone(response)
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("non-empty string", response["error"]["message"])

    def test_tools_call_rejects_empty_name(self) -> None:
        response = agentmemory_mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "", "arguments": {}},
            }
        )
        self.assertIsNotNone(response)
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32602)

    def test_tools_call_rejects_non_string_name(self) -> None:
        response = agentmemory_mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": 42, "arguments": {}},
            }
        )
        self.assertIsNotNone(response)
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32602)

    def test_tools_call_rejects_non_dict_arguments(self) -> None:
        response = agentmemory_mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "memory_health", "arguments": "bad"},
            }
        )
        self.assertIsNotNone(response)
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("JSON object", response["error"]["message"])

    def test_tools_call_rejects_list_arguments(self) -> None:
        response = agentmemory_mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "memory_health", "arguments": [1, 2]},
            }
        )
        self.assertIsNotNone(response)
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32602)

    def test_tools_call_accepts_valid_name_and_arguments(self) -> None:
        original_spec = agentmemory_mcp.OPERATIONS_BY_MCP_NAME["memory_health"]
        try:
            agentmemory_mcp.OPERATIONS_BY_MCP_NAME["memory_health"] = agentmemory_operations.OperationSpec(
                name="health",
                mcp_name="memory_health",
                title="Memory Health",
                description="Return runtime information.",
                input_schema=original_spec.input_schema,
                execute=lambda source: {"ok": True},
            )
            response = agentmemory_mcp.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {"name": "memory_health", "arguments": {}},
                }
            )
        finally:
            agentmemory_mcp.OPERATIONS_BY_MCP_NAME["memory_health"] = original_spec

        self.assertIsNotNone(response)
        self.assertIn("result", response)
        self.assertFalse(response["result"]["isError"])

    def test_tools_call_with_missing_arguments_defaults_to_empty_dict(self) -> None:
        original_spec = agentmemory_mcp.OPERATIONS_BY_MCP_NAME["memory_health"]
        try:
            agentmemory_mcp.OPERATIONS_BY_MCP_NAME["memory_health"] = agentmemory_operations.OperationSpec(
                name="health",
                mcp_name="memory_health",
                title="Memory Health",
                description="Return runtime information.",
                input_schema=original_spec.input_schema,
                execute=lambda source: {"ok": True},
            )
            response = agentmemory_mcp.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "memory_health"},
                }
            )
        finally:
            agentmemory_mcp.OPERATIONS_BY_MCP_NAME["memory_health"] = original_spec

        self.assertIsNotNone(response)
        self.assertIn("result", response)
        self.assertFalse(response["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
