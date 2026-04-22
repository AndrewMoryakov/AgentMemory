import io
import json
import sys
import tempfile
import unittest

import agentmemory.ops_cli as agentmemory_cli
import agentmemory.runtime.operations as agentmemory_operations
from agentmemory.providers.localjson import LocalJsonProvider
from agentmemory.providers.mem0 import Mem0Provider
from agentmemory.providers.base import (
    MemoryNotFoundError,
    ProviderCapabilityError,
    ProviderScopeRequiredError,
    ProviderValidationError,
)


class Mem0ProviderContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.provider = Mem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_add_memory_fails_closed_on_empty_payload(self) -> None:
        self.provider._load_memory = lambda: type(  # type: ignore[method-assign]
            "FakeMemory",
            (),
            {
                "add": lambda *args, **kwargs: [],
                "get_all": lambda *args, **kwargs: [],
            },
        )()

        with self.assertRaises(ProviderValidationError):
            self.provider.add_memory(messages=[{"role": "user", "content": "hello"}], user_id="demo")

    def test_get_memory_fails_closed_on_payload_without_id(self) -> None:
        self.provider._load_memory = lambda: type(  # type: ignore[method-assign]
            "FakeMemory",
            (),
            {"get": lambda *args, **kwargs: {"memory": "hello"}},
        )()

        with self.assertRaises(ProviderValidationError):
            self.provider.get_memory("missing")

    def test_update_memory_fails_closed_on_invalid_payload(self) -> None:
        self.provider._load_memory = lambda: type(  # type: ignore[method-assign]
            "FakeMemory",
            (),
            {"update": lambda *args, **kwargs: {}},
        )()

        with self.assertRaises(ProviderValidationError):
            self.provider.update_memory(memory_id="demo", data="new")

    def test_delete_memory_fails_closed_on_invalid_payload(self) -> None:
        self.provider._load_memory = lambda: type(  # type: ignore[method-assign]
            "FakeMemory",
            (),
            {"delete": lambda *args, **kwargs: {"ok": True}},
        )()

        with self.assertRaises(ProviderValidationError):
            self.provider.delete_memory(memory_id="demo")

    def test_map_exception_converts_scope_error(self) -> None:
        exc = RuntimeError("At least one of 'user_id', 'agent_id', or 'run_id' must be provided.")

        mapped = self.provider._map_exception(exc)

        self.assertIsInstance(mapped, ProviderScopeRequiredError)

    def test_map_exception_preserves_typed_memory_not_found(self) -> None:
        exc = MemoryNotFoundError("missing")

        mapped = self.provider._map_exception(exc)

        self.assertIs(mapped, exc)


class LocalJsonProviderContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.provider = LocalJsonProvider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=LocalJsonProvider.default_provider_config(runtime_dir=self.temp_dir.name),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_localjson_rejects_unsupported_rerank(self) -> None:
        with self.assertRaises(ProviderCapabilityError):
            self.provider.search_memory(query="demo", rerank=True)


class AgentMemoryCliValidationTests(unittest.TestCase):
    def test_parse_metadata_raises_typed_validation_error(self) -> None:
        with self.assertRaises(ProviderValidationError):
            agentmemory_cli.parse_metadata("{")

    def test_cli_returns_exit_code_2_for_invalid_metadata(self) -> None:
        original_argv = sys.argv
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        try:
            sys.argv = ["agentmemory_cli.py", "add", "--message", "hello", "--metadata", "{"]
            sys.stdout = stdout_buffer
            sys.stderr = stderr_buffer
            rc = agentmemory_cli.main()
        finally:
            sys.argv = original_argv
            sys.stdout = original_stdout
            sys.stderr = original_stderr

        self.assertEqual(rc, 2)
        payload = json.loads(stderr_buffer.getvalue())
        self.assertEqual(payload["error_type"], "ProviderValidationError")
        self.assertIn("Invalid JSON", payload["message"])

    def test_cli_returns_exit_code_2_for_invalid_filters(self) -> None:
        original_argv = sys.argv
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        try:
            sys.argv = ["agentmemory_cli.py", "list", "--filters", "{"]
            sys.stdout = stdout_buffer
            sys.stderr = stderr_buffer
            rc = agentmemory_cli.main()
        finally:
            sys.argv = original_argv
            sys.stdout = original_stdout
            sys.stderr = original_stderr

        self.assertEqual(rc, 2)
        payload = json.loads(stderr_buffer.getvalue())
        self.assertEqual(payload["error_type"], "ProviderValidationError")
        self.assertIn("Invalid JSON", payload["message"])

    def test_cli_export_prints_structured_success_payload(self) -> None:
        original_argv = sys.argv
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        original_spec = agentmemory_operations.OPERATIONS["export"]
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        try:
            sys.argv = ["agentmemory_cli.py", "export", "memories.jsonl"]
            sys.stdout = stdout_buffer
            sys.stderr = stderr_buffer
            agentmemory_operations.OPERATIONS["export"] = original_spec.__class__(
                name="export",
                mcp_name="memory_export",
                title="Export Memories",
                description="Export memories.",
                input_schema=original_spec.input_schema,
                execute=lambda source: {"path": source["path"], "exported": 2},
            )
            rc = agentmemory_cli.main()
        finally:
            sys.argv = original_argv
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            agentmemory_operations.OPERATIONS["export"] = original_spec

        self.assertEqual(rc, 0)
        payload = json.loads(stdout_buffer.getvalue())
        self.assertEqual(payload["path"], "memories.jsonl")
        self.assertEqual(payload["exported"], 2)

    def test_cli_reconcile_prints_structured_success_payload(self) -> None:
        original_argv = sys.argv
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        original_spec = agentmemory_operations.OPERATIONS["reconcile"]
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        try:
            sys.argv = ["agentmemory_cli.py", "reconcile", "--user-id", "u1"]
            sys.stdout = stdout_buffer
            sys.stderr = stderr_buffer
            agentmemory_operations.OPERATIONS["reconcile"] = original_spec.__class__(
                name="reconcile",
                mcp_name="memory_reconcile",
                title="Reconcile Memories",
                description="Reconcile memories.",
                input_schema=original_spec.input_schema,
                execute=lambda source: {"user_id": source["user_id"], "conflict_count": 1},
            )
            rc = agentmemory_cli.main()
        finally:
            sys.argv = original_argv
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            agentmemory_operations.OPERATIONS["reconcile"] = original_spec

        self.assertEqual(rc, 0)
        payload = json.loads(stdout_buffer.getvalue())
        self.assertEqual(payload["user_id"], "u1")
        self.assertEqual(payload["conflict_count"], 1)

    def test_cli_search_rejects_missing_required_scope_before_provider_call(self) -> None:
        original_argv = sys.argv
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        original_capabilities = agentmemory_operations.active_provider_capabilities
        original_provider_name = agentmemory_operations.active_provider_name
        original_search_spec = agentmemory_operations.OPERATIONS["search"]
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        try:
            sys.argv = ["agentmemory_cli.py", "search", "demo"]
            sys.stdout = stdout_buffer
            sys.stderr = stderr_buffer
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
            agentmemory_operations.active_provider_name = lambda: "mem0"  # type: ignore[assignment]
            agentmemory_operations.OPERATIONS["search"] = original_search_spec
            rc = agentmemory_cli.main()
        finally:
            sys.argv = original_argv
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            agentmemory_operations.active_provider_capabilities = original_capabilities  # type: ignore[assignment]
            agentmemory_operations.active_provider_name = original_provider_name  # type: ignore[assignment]
            agentmemory_operations.OPERATIONS["search"] = original_search_spec

        self.assertEqual(rc, 2)
        payload = json.loads(stderr_buffer.getvalue())
        self.assertEqual(payload["error_type"], "ProviderValidationError")
        self.assertIn("requires user_id, agent_id, or run_id for search", payload["message"])

    def test_cli_search_coerces_unsupported_rerank_before_provider_call(self) -> None:
        # Per DEFECT-01 the capability gap no longer raises; the dispatcher
        # silently coerces rerank=True to False so the tool's default isn't
        # hostile to providers that lack rerank.
        original_argv = sys.argv
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        original_capabilities = agentmemory_operations.active_provider_capabilities
        original_provider_name = agentmemory_operations.active_provider_name
        original_memory_search = agentmemory_operations.memory_search
        captured: dict = {}

        def fake_memory_search(**kwargs):
            captured.update(kwargs)
            return []

        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        try:
            sys.argv = ["agentmemory_cli.py", "search", "demo", "--user-id", "u1"]
            sys.stdout = stdout_buffer
            sys.stderr = stderr_buffer
            agentmemory_operations.active_provider_capabilities = lambda: {  # type: ignore[assignment]
                "supports_semantic_search": False,
                "supports_text_search": True,
                "supports_filters": True,
                "supports_metadata_filters": True,
                "supports_rerank": False,
                "supports_update": True,
                "supports_delete": True,
                "supports_scopeless_list": True,
                "requires_scope_for_list": False,
                "requires_scope_for_search": False,
                "supports_owner_process_mode": False,
                "supports_scope_inventory": True,
            }
            agentmemory_operations.active_provider_name = lambda: "localjson"  # type: ignore[assignment]
            agentmemory_operations.memory_search = fake_memory_search  # type: ignore[assignment]
            rc = agentmemory_cli.main()
        finally:
            sys.argv = original_argv
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            agentmemory_operations.active_provider_capabilities = original_capabilities  # type: ignore[assignment]
            agentmemory_operations.active_provider_name = original_provider_name  # type: ignore[assignment]
            agentmemory_operations.memory_search = original_memory_search  # type: ignore[assignment]

        self.assertEqual(rc, 0)
        self.assertNotIn("does not support rerank", stderr_buffer.getvalue())
        self.assertEqual(captured.get("rerank"), False)


if __name__ == "__main__":
    unittest.main()
