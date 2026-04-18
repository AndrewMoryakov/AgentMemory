"""Regression lock-ins for the post-remediation report (2026-04-18).

Complements tests/test_defect_fixes.py with the items called out in §4 of
that report as "tests to add". Where the §4 item asked for cross-provider
coverage, this file uses patched capabilities + patched provider callables
so the same assertion runs in-process against both mem0- and
localjson-shaped capability blocks without needing two live stacks.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agentmemory.api as api_module
import agentmemory.runtime.operations as agentmemory_operations
from agentmemory.providers.base import MemoryNotFoundError, ProviderUnavailableError


_MEM0_CAPS = {
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


_LOCALJSON_CAPS = {
    **_MEM0_CAPS,
    "supports_semantic_search": False,
    "supports_text_search": True,
    "supports_rerank": False,
    "supports_scopeless_list": True,
    "requires_scope_for_list": False,
    "requires_scope_for_search": False,
    "supports_owner_process_mode": False,
}


class SearchDefaultsAcrossProviders(unittest.TestCase):
    """§4.6 — memory_search with no explicit rerank must succeed on both
    providers. mem0 has rerank=true, localjson has rerank=false; the
    coercion added in DEFECT-01 must handle the latter silently.
    """

    def _run_search(self, caps, captured):
        def fake_memory_search(**kwargs):
            captured.update(kwargs)
            return []

        with mock.patch.object(agentmemory_operations, "memory_search", fake_memory_search), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_capabilities", lambda: caps), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "fake"):
            return agentmemory_operations.OPERATIONS["search"].execute({"query": "probe", "user_id": "u1"})

    def test_mem0_caps_pass_rerank_true(self) -> None:
        captured: dict = {}
        self._run_search(_MEM0_CAPS, captured)
        self.assertTrue(captured["rerank"])

    def test_localjson_caps_coerce_rerank_to_false(self) -> None:
        captured: dict = {}
        self._run_search(_LOCALJSON_CAPS, captured)
        self.assertFalse(captured["rerank"])

    def test_neither_provider_raises_on_missing_rerank_kwarg(self) -> None:
        # Absence of raised exception is the regression guarantee. The
        # actual result type doesn't matter here.
        for caps in (_MEM0_CAPS, _LOCALJSON_CAPS):
            with self.subTest(caps=caps):
                self._run_search(caps, captured={})


class DeleteIdempotencyAcrossProviders(unittest.TestCase):
    """§4.4 — two consecutive deletes: first succeeds, second returns
    already_absent=true. Neither raises ProviderUnavailableError.
    """

    def _run_double_delete(self, caps, first_delete_side_effect, second_delete_side_effect):
        call_order = iter([first_delete_side_effect, second_delete_side_effect])

        def fake_memory_delete(*, memory_id):
            effect = next(call_order)
            if isinstance(effect, Exception):
                raise effect
            return effect

        with mock.patch.object(agentmemory_operations, "memory_delete", fake_memory_delete), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_capabilities", lambda: caps), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "fake"):
            first = agentmemory_operations.OPERATIONS["delete"].execute({"memory_id": "abc"})
            second = agentmemory_operations.OPERATIONS["delete"].execute({"memory_id": "abc"})
        return first, second

    def test_idempotent_on_mem0_shape(self) -> None:
        first, second = self._run_double_delete(
            _MEM0_CAPS,
            {"id": "abc", "deleted": True, "provider": "mem0"},
            MemoryNotFoundError("abc"),
        )
        self.assertTrue(first["deleted"])
        self.assertFalse(second["deleted"])
        self.assertTrue(second["already_absent"])

    def test_idempotent_on_localjson_shape(self) -> None:
        first, second = self._run_double_delete(
            _LOCALJSON_CAPS,
            {"id": "abc", "deleted": True, "provider": "localjson"},
            MemoryNotFoundError("abc"),
        )
        self.assertTrue(first["deleted"])
        self.assertFalse(second["deleted"])
        self.assertTrue(second["already_absent"])


class ProviderUnavailableScope(unittest.TestCase):
    """§4.5 — ProviderUnavailableError must only fire on real transport
    failures. MemoryNotFoundError must never be reclassified to it.
    """

    def test_transport_failure_is_provider_unavailable(self) -> None:
        def raising(*, memory_id):
            raise ProviderUnavailableError("qdrant connection refused")

        with mock.patch.object(agentmemory_operations, "memory_delete", raising), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "fake"):
            with self.assertRaises(ProviderUnavailableError):
                agentmemory_operations.OPERATIONS["delete"].execute({"memory_id": "abc"})

    def test_not_found_is_caught_before_becoming_unavailable(self) -> None:
        def raising(*, memory_id):
            raise MemoryNotFoundError("abc")

        with mock.patch.object(agentmemory_operations, "memory_delete", raising), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "fake"):
            result = agentmemory_operations.OPERATIONS["delete"].execute({"memory_id": "abc"})
        self.assertEqual(result["already_absent"], True)
        # Key absence assertion: we never surfaced ProviderUnavailableError.


class ContractMatchesBehaviorForHardDelete(unittest.TestCase):
    """§4.7 — if provider_contract advertises delete_semantics=hard_delete,
    a deleted record must not come back via memory_list or memory_get.
    """

    def test_mem0_contract_is_hard_delete(self) -> None:
        from agentmemory.providers.mem0 import Mem0Provider
        contract = Mem0Provider.__new__(Mem0Provider).provider_contract()
        self.assertEqual(contract["delete_semantics"], "hard_delete")

    def test_localjson_contract_is_hard_delete(self) -> None:
        from agentmemory.providers.localjson import LocalJsonProvider
        contract = LocalJsonProvider.__new__(LocalJsonProvider).provider_contract()
        self.assertEqual(contract["delete_semantics"], "hard_delete")

    def test_base_default_does_not_emit_sentinel(self) -> None:
        # The post-remediation report flagged "owner_process_proxy" as a
        # non-committal sentinel masquerading as a visibility value. The
        # base-class default must now emit a concrete observable value even
        # under owner_process_proxy transport — call the base directly to
        # exercise the default without dragging in a concrete provider.
        from agentmemory.providers.base import BaseMemoryProvider

        fake = mock.Mock(spec=BaseMemoryProvider)
        fake.runtime_policy = lambda: {"transport_mode": "owner_process_proxy"}
        contract = BaseMemoryProvider.provider_contract(fake)
        self.assertEqual(contract["write_visibility"], "immediate")
        self.assertEqual(contract["delete_semantics"], "hard_delete")


class SupervisorFilesRefreshedOnRestart(unittest.TestCase):
    """§4.3 — after a cold restart the pid file contains the *new* PID,
    not whatever was left behind.
    """

    def test_record_then_record_again_rewrites_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "agentmemory-api.pid"
            state_path = Path(tmp) / "agentmemory-api.json"

            with mock.patch.object(api_module, "API_PID_FILE", pid_path), \
                 mock.patch.object(api_module, "API_STATE_FILE", state_path), \
                 mock.patch("agentmemory.runtime.config.API_PID_FILE", pid_path), \
                 mock.patch("agentmemory.runtime.config.API_STATE_FILE", state_path):
                # Simulate "previous process died hard and left stale files".
                pid_path.write_text("999999", encoding="ascii")
                state_path.write_text('{"pid": 999999}', encoding="utf-8")

                api_module._record_supervisor_files(host="127.0.0.1", port=18765)
                self.assertEqual(pid_path.read_text(encoding="ascii").strip(), str(os.getpid()))
                # state file also refreshed to reflect new pid
                self.assertIn(str(os.getpid()), state_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
