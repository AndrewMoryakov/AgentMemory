import unittest

import agentmemory_operations
import agentmemory_mcp_server
from memory_provider import MemoryNotFoundError, ProviderCapabilityError, ProviderScopeRequiredError


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
        self.assertIn("memory_list_scopes", tool_names)

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

    def test_provider_errors_return_structured_error_payload(self) -> None:
        original_spec = agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_get"]
        try:
            agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_get"] = agentmemory_operations.OperationSpec(
                name="get",
                mcp_name="memory_get",
                title="Get Memory",
                description="Get one memory by id.",
                input_schema=original_spec.input_schema,
                execute=lambda source: (_ for _ in ()).throw(MemoryNotFoundError("missing")),
            )
            response = agentmemory_mcp_server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "memory_get", "arguments": {"memory_id": "missing"}},
                }
            )
        finally:
            agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_get"] = original_spec

        self.assertIsNotNone(response)
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error_type"], "MemoryNotFoundError")
        self.assertEqual(result["structuredContent"]["message"], "missing")

    def test_scope_required_errors_return_structured_error_payload(self) -> None:
        original_spec = agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_search"]
        try:
            agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_search"] = agentmemory_operations.OperationSpec(
                name="search",
                mcp_name="memory_search",
                title="Search Memory",
                description="Search shared memory semantically.",
                input_schema=original_spec.input_schema,
                execute=lambda source: (_ for _ in ()).throw(ProviderScopeRequiredError("scope required")),
            )
            response = agentmemory_mcp_server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "memory_search", "arguments": {"query": "demo"}},
                }
            )
        finally:
            agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_search"] = original_spec

        self.assertIsNotNone(response)
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error_type"], "ProviderScopeRequiredError")

    def test_capability_errors_return_structured_error_payload(self) -> None:
        original_spec = agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_search"]
        try:
            agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_search"] = agentmemory_operations.OperationSpec(
                name="search",
                mcp_name="memory_search",
                title="Search Memory",
                description="Search shared memory semantically.",
                input_schema=original_spec.input_schema,
                execute=lambda source: (_ for _ in ()).throw(ProviderCapabilityError("unsupported rerank")),
            )
            response = agentmemory_mcp_server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {"name": "memory_search", "arguments": {"query": "demo"}},
                }
            )
        finally:
            agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_search"] = original_spec

        self.assertIsNotNone(response)
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error_type"], "ProviderCapabilityError")

    def test_search_validation_errors_use_shared_transport_validation(self) -> None:
        original_spec = agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_search"]
        original_caps = agentmemory_operations.active_provider_capabilities
        original_provider_name = agentmemory_operations.active_provider_name
        try:
            agentmemory_operations.active_provider_name = lambda: "mem0"  # type: ignore[assignment]
            agentmemory_operations.active_provider_capabilities = lambda: {  # type: ignore[assignment]
                "supports_semantic_search": True,
                "supports_text_search": False,
                "supports_filters": True,
                "supports_metadata_filters": True,
                "supports_rerank": True,
                "supports_update": True,
                "supports_delete": True,
                "supports_scopeless_list": False,
                "requires_scope_for_list": True,
                "requires_scope_for_search": True,
                "supports_owner_process_mode": True,
                "supports_scope_inventory": True,
            }
            agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_search"] = original_spec
            response = agentmemory_mcp_server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "memory_search", "arguments": {"query": "demo"}},
                }
            )
        finally:
            agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_search"] = original_spec
            agentmemory_operations.active_provider_capabilities = original_caps  # type: ignore[assignment]
            agentmemory_operations.active_provider_name = original_provider_name  # type: ignore[assignment]

        self.assertIsNotNone(response)
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error_type"], "ProviderValidationError")

    def test_list_scopes_call_returns_structured_success_payload(self) -> None:
        original_spec = agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_list_scopes"]
        try:
            agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_list_scopes"] = agentmemory_operations.OperationSpec(
                name="list_scopes",
                mcp_name="memory_list_scopes",
                title="List Scopes",
                description="List known user, agent, and run scopes for the active provider.",
                input_schema=original_spec.input_schema,
                execute=lambda source: {"provider": "demo", "items": [], "totals": {"users": 0, "agents": 0, "runs": 0}, **source},
            )
            response = agentmemory_mcp_server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 8,
                    "method": "tools/call",
                    "params": {"name": "memory_list_scopes", "arguments": {"limit": 25, "kind": "user", "query": "def"}},
                }
            )
        finally:
            agentmemory_mcp_server.OPERATIONS_BY_MCP_NAME["memory_list_scopes"] = original_spec

        self.assertIsNotNone(response)
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["provider"], "demo")


if __name__ == "__main__":
    unittest.main()
