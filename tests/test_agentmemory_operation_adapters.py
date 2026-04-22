import argparse
import unittest

from agentmemory.runtime.operation_adapters import (
    cli_operation_source,
    http_operation_source,
    mcp_operation_source,
    operation_name_for_mcp_tool,
)
from agentmemory.providers.base import ProviderValidationError


class AgentMemoryOperationAdaptersTests(unittest.TestCase):
    def test_operation_name_for_mcp_tool_normalizes_prefix(self) -> None:
        self.assertEqual(operation_name_for_mcp_tool("memory_search"), "search")

    def test_operation_name_for_mcp_tool_rejects_unknown_prefix(self) -> None:
        with self.assertRaises(ProviderValidationError):
            operation_name_for_mcp_tool("search")

    def test_cli_operation_source_builds_add_payload(self) -> None:
        args = argparse.Namespace(
            message=["hello", "world"],
            user_id="u1",
            agent_id=None,
            run_id=None,
            metadata='{"topic":"docs"}',
            infer=True,
            memory_type="preference",
        )
        source = cli_operation_source("add", args, parse_json_arg=lambda raw: {"topic": "docs"} if raw else None)

        self.assertEqual(source["messages"][0]["content"], "hello")
        self.assertEqual(source["messages"][1]["content"], "world")
        self.assertEqual(source["metadata"], {"topic": "docs"})
        self.assertTrue(source["infer"])

    def test_cli_operation_source_defaults_add_infer_to_false(self) -> None:
        args = argparse.Namespace(
            message=["hello"],
            user_id="u1",
            agent_id=None,
            run_id=None,
            metadata=None,
            memory_type=None,
        )
        source = cli_operation_source("add", args, parse_json_arg=lambda raw: None)

        self.assertFalse(source["infer"])

    def test_cli_operation_source_builds_list_scopes_payload(self) -> None:
        args = argparse.Namespace(limit=25, kind="user", query="def")

        source = cli_operation_source("list-scopes", args, parse_json_arg=lambda raw: raw)

        self.assertEqual(source, {"limit": 25, "kind": "user", "query": "def"})

    def test_cli_operation_source_builds_export_payload(self) -> None:
        args = argparse.Namespace(path="memories.jsonl")

        source = cli_operation_source("export", args, parse_json_arg=lambda raw: raw)

        self.assertEqual(source, {"path": "memories.jsonl"})

    def test_cli_operation_source_builds_reconcile_payload(self) -> None:
        args = argparse.Namespace(user_id="u1", agent_id=None, run_id=None, limit=50, filters='{"topic":"prefs"}')

        source = cli_operation_source("reconcile", args, parse_json_arg=lambda raw: {"topic": "prefs"} if raw else None)

        self.assertEqual(source, {"user_id": "u1", "agent_id": None, "run_id": None, "limit": 50, "filters": {"topic": "prefs"}})

    def test_mcp_operation_source_builds_add_messages_from_text(self) -> None:
        source = mcp_operation_source("memory_add", {"text": "hello", "user_id": "u1"})

        self.assertEqual(source["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(source["user_id"], "u1")

    def test_http_operation_source_builds_list_source(self) -> None:
        source = http_operation_source(
            "list",
            query_params={
                "user_id": ["u1"],
                "limit": ["25"],
                "filters": ['{"topic":"docs"}'],
            },
        )

        self.assertEqual(source["user_id"], "u1")
        self.assertEqual(source["limit"], 25)
        self.assertEqual(source["filters"], {"topic": "docs"})

    def test_http_operation_source_builds_list_scopes_source(self) -> None:
        source = http_operation_source(
            "list_scopes",
            query_params={
                "limit": ["25"],
                "kind": ["user"],
                "query": ["def"],
            },
        )

        self.assertEqual(source, {"limit": 25, "kind": "user", "query": "def"})

    def test_http_operation_source_rejects_invalid_filters_json(self) -> None:
        with self.assertRaises(ProviderValidationError):
            http_operation_source("list", query_params={"filters": ["{"]})


if __name__ == "__main__":
    unittest.main()
