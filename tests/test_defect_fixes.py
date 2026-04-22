"""Regression tests for the defects called out in the 2026-04-18 MCP diagnostic.

Each test is scoped to a single defect so a future regression points directly
at the code that changed. Where unit coverage isn't enough (supervisor files,
full mem0 round-trips), see docs/DEPLOY.md's §5-style smoke steps.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agentmemory.runtime.operations as agentmemory_operations
from agentmemory.providers.base import MemoryNotFoundError
from agentmemory.runtime.transport import validate_and_build_search_kwargs


_BASE_CAPS = {
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
                "supports_pagination": False,
}


def _caps(**overrides):
    caps = dict(_BASE_CAPS)
    caps.update(overrides)
    return caps


class Defect04AddInferDefaults(unittest.TestCase):
    """DEFECT-04: memory_add used to default infer=True and silently rewrite."""

    def test_schema_defaults_infer_to_false(self) -> None:
        schema = agentmemory_operations.OPERATIONS["add"].input_schema
        self.assertEqual(schema["properties"]["infer"]["default"], False)

    def test_description_mentions_infer_semantics(self) -> None:
        description = agentmemory_operations.OPERATIONS["add"].description.lower()
        self.assertIn("infer", description)
        self.assertIn("verbatim", description)

    def test_execute_add_without_infer_passes_false_to_provider(self) -> None:
        captured = {}

        def fake_memory_add(**kwargs):
            captured.update(kwargs)
            return {"id": "m1", "memory": "stored", "provider": "fake"}

        with mock.patch.object(agentmemory_operations, "memory_add", fake_memory_add), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False):
            agentmemory_operations.OPERATIONS["add"].execute({
                "messages": [{"role": "user", "content": "hello"}],
                "text": "hello",
                "user_id": "u1",
            })
        self.assertEqual(captured.get("infer"), False)

    def test_execute_add_surfaces_transform_when_infer_true(self) -> None:
        def fake_memory_add(**_kwargs):
            return {"id": "m1", "memory": "Summarized form", "provider": "fake"}

        with mock.patch.object(agentmemory_operations, "memory_add", fake_memory_add), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False):
            result = agentmemory_operations.OPERATIONS["add"].execute({
                "messages": [{"role": "user", "content": "Original long input"}],
                "text": "Original long input",
                "user_id": "u1",
                "infer": True,
            })
        self.assertTrue(result.get("transformed"))
        self.assertEqual(result.get("original_text"), "Original long input")
        self.assertEqual(result.get("stored_text"), "Summarized form")

    def test_execute_add_does_not_surface_transform_when_stored_matches(self) -> None:
        def fake_memory_add(**_kwargs):
            return {"id": "m1", "memory": "exact input", "provider": "fake"}

        with mock.patch.object(agentmemory_operations, "memory_add", fake_memory_add), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False):
            result = agentmemory_operations.OPERATIONS["add"].execute({
                "messages": [{"role": "user", "content": "exact input"}],
                "text": "exact input",
                "user_id": "u1",
                "infer": True,
            })
        self.assertNotIn("transformed", result)
        self.assertNotIn("original_text", result)

    def test_execute_add_does_not_surface_transform_when_infer_false(self) -> None:
        def fake_memory_add(**_kwargs):
            # Even if the provider hypothetically rewrote, the caller asked
            # for verbatim, so we don't tag the response as transformed.
            return {"id": "m1", "memory": "different", "provider": "fake"}

        with mock.patch.object(agentmemory_operations, "memory_add", fake_memory_add), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False):
            result = agentmemory_operations.OPERATIONS["add"].execute({
                "messages": [{"role": "user", "content": "exact input"}],
                "text": "exact input",
                "user_id": "u1",
            })
        self.assertNotIn("transformed", result)


class Defect01RerankCapabilityCoercion(unittest.TestCase):
    """DEFECT-01: rerank default must not raise on providers that lack rerank."""

    def test_rerank_coerced_to_false_when_provider_lacks_rerank(self) -> None:
        caps = _caps(supports_rerank=False)
        kwargs = validate_and_build_search_kwargs(
            provider_name="localjson",
            capabilities=caps,
            source={"query": "demo", "user_id": "u1"},
        )
        self.assertFalse(kwargs["rerank"])

    def test_rerank_preserved_when_provider_supports_rerank(self) -> None:
        caps = _caps(supports_rerank=True)
        kwargs = validate_and_build_search_kwargs(
            provider_name="mem0",
            capabilities=caps,
            source={"query": "demo", "user_id": "u1"},
        )
        self.assertTrue(kwargs["rerank"])

    def test_rerank_explicit_false_stays_false(self) -> None:
        caps = _caps(supports_rerank=True)
        kwargs = validate_and_build_search_kwargs(
            provider_name="mem0",
            capabilities=caps,
            source={"query": "demo", "user_id": "u1", "rerank": False},
        )
        self.assertFalse(kwargs["rerank"])


class Defect03DeleteIdempotentAndTyped(unittest.TestCase):
    """DEFECT-03: double-delete returns idempotent payload instead of raising."""

    def test_delete_of_absent_record_returns_already_absent(self) -> None:
        def fake_memory_delete(*, memory_id):
            raise MemoryNotFoundError(memory_id)

        with mock.patch.object(agentmemory_operations, "memory_delete", fake_memory_delete), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "mem0"):
            result = agentmemory_operations.OPERATIONS["delete"].execute({"memory_id": "abc"})

        self.assertEqual(result["id"], "abc")
        self.assertEqual(result["deleted"], False)
        self.assertEqual(result["already_absent"], True)
        self.assertEqual(result["provider"], "mem0")

    def test_delete_of_present_record_flows_through(self) -> None:
        def fake_memory_delete(*, memory_id):
            return {"id": memory_id, "deleted": True, "provider": "mem0"}

        with mock.patch.object(agentmemory_operations, "memory_delete", fake_memory_delete), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False):
            result = agentmemory_operations.OPERATIONS["delete"].execute({"memory_id": "abc"})

        self.assertTrue(result["deleted"])
        self.assertNotIn("already_absent", result)


class Defect03Mem0ErrorClassification(unittest.TestCase):
    """DEFECT-03: mem0 _map_exception must prefer MemoryNotFoundError over ProviderUnavailableError."""

    def test_not_found_in_message_maps_to_memory_not_found(self) -> None:
        from agentmemory.providers.base import (
            MemoryNotFoundError as _MemoryNotFoundError,
            ProviderUnavailableError,
        )
        from agentmemory.providers.mem0 import Mem0Provider

        mapped = Mem0Provider._map_exception.__get__(
            # Bind to a dummy instance since _map_exception only inspects exc
            mock.Mock(spec=Mem0Provider),
            Mem0Provider,
        )(RuntimeError("Memory with id abc not found"))
        self.assertIsInstance(mapped, _MemoryNotFoundError)

    def test_qdrant_lock_still_maps_to_provider_unavailable(self) -> None:
        from agentmemory.providers.base import ProviderUnavailableError
        from agentmemory.providers.mem0 import Mem0Provider

        mapped = Mem0Provider._map_exception.__get__(
            mock.Mock(spec=Mem0Provider),
            Mem0Provider,
        )(RuntimeError("Storage folder ... is already accessed by another instance of Qdrant client."))
        self.assertIsInstance(mapped, ProviderUnavailableError)


class Defect05Mem0ContractHonesty(unittest.TestCase):
    """DEFECT-05: mem0 advertises hard_delete + immediate, matching observed behavior."""

    def test_contract_reports_hard_delete_and_immediate_writes(self) -> None:
        from agentmemory.providers.mem0 import Mem0Provider

        # The provider_contract method doesn't touch state or config, so a
        # bare instance is enough.
        provider = Mem0Provider.__new__(Mem0Provider)
        contract = provider.provider_contract()

        self.assertEqual(contract["delete_semantics"], "hard_delete")
        self.assertEqual(contract["write_visibility"], "immediate")
        self.assertEqual(contract["consistency"], "immediate")


class Defect02SupervisorFiles(unittest.TestCase):
    """DEFECT-02: api.main() writes pid + state files at listener bind and cleans up."""

    def test_record_then_cleanup_cycle(self) -> None:
        import agentmemory.api as api_module

        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "agentmemory-api.pid"
            state_path = Path(tmp) / "agentmemory-api.json"

            with mock.patch.object(api_module, "API_PID_FILE", pid_path), \
                 mock.patch.object(api_module, "API_STATE_FILE", state_path), \
                 mock.patch("agentmemory.runtime.config.API_PID_FILE", pid_path), \
                 mock.patch("agentmemory.runtime.config.API_STATE_FILE", state_path):
                api_module._record_supervisor_files(host="127.0.0.1", port=18765)
                self.assertTrue(pid_path.exists())
                self.assertEqual(pid_path.read_text(encoding="ascii").strip(), str(__import__("os").getpid()))
                self.assertTrue(state_path.exists())

                api_module._cleanup_supervisor_files()
                self.assertFalse(pid_path.exists())
                self.assertFalse(state_path.exists())


if __name__ == "__main__":
    unittest.main()
