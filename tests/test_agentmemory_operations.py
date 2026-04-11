import unittest

import agentmemory_operations
from memory_provider import ProviderValidationError


class AgentMemoryOperationsTests(unittest.TestCase):
    def test_registry_contains_expected_core_operations(self) -> None:
        self.assertEqual(
            set(agentmemory_operations.OPERATIONS.keys()),
            {"health", "add", "list_scopes", "search", "list", "get", "update", "delete"},
        )

    def test_mcp_tools_are_derived_from_operation_registry(self) -> None:
        tool_names = {tool["name"] for tool in agentmemory_operations.mcp_tools()}
        self.assertEqual(tool_names, {spec.mcp_name for spec in agentmemory_operations.OPERATIONS.values()})

    def test_search_operation_uses_shared_validation_path(self) -> None:
        original_name = agentmemory_operations.active_provider_name
        original_caps = agentmemory_operations.active_provider_capabilities
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
            with self.assertRaises(ProviderValidationError):
                agentmemory_operations.OPERATIONS["search"].execute({"query": "demo"})
        finally:
            agentmemory_operations.active_provider_name = original_name  # type: ignore[assignment]
            agentmemory_operations.active_provider_capabilities = original_caps  # type: ignore[assignment]

    def test_list_scopes_operation_schema_accepts_limit_kind_query(self) -> None:
        schema = agentmemory_operations.OPERATIONS["list_scopes"].input_schema

        self.assertIn("limit", schema["properties"])
        self.assertIn("kind", schema["properties"])
        self.assertIn("query", schema["properties"])


if __name__ == "__main__":
    unittest.main()
