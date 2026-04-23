"""Tests for the observability (metrics) and lifecycle (TTL, dedup) features.

Unit-scoped, no network. Runs cleanly on both mem0 and localjson configs in
CI because they patch transport/provider callables inline.
"""

from __future__ import annotations

import time
import unittest
from datetime import timedelta
from unittest import mock

import agentmemory.runtime.operations as agentmemory_operations
from agentmemory.runtime import lifecycle as lifecycle_module
from agentmemory.runtime import metrics as metrics_module


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


class MetricsRegistryTests(unittest.TestCase):
    def test_record_operation_populates_summary_and_prometheus(self) -> None:
        registry = metrics_module._MetricsRegistry()
        registry.record_operation(name="search", status="ok", duration_seconds=0.15)
        registry.record_operation(name="search", status="ok", duration_seconds=0.42)
        registry.record_operation(
            name="add", status="error", duration_seconds=0.05, error_type="ProviderScopeRequiredError"
        )
        registry.record_event(name="memory_add.dedup_hit")

        summary = registry.summary()
        self.assertEqual(summary["operations"]["search"]["ok"], 2)
        self.assertEqual(summary["operations"]["search"]["errors"], 0)
        self.assertGreater(summary["operations"]["search"]["latency_avg_ms"], 100)
        self.assertEqual(summary["operations"]["add"]["ok"], 0)
        self.assertEqual(summary["operations"]["add"]["errors"], 1)
        self.assertEqual(summary["events"]["memory_add.dedup_hit"], 1)

        prom = registry.prometheus_text()
        self.assertIn('agentmemory_operation_ok_total{operation="search"} 2', prom)
        self.assertIn('agentmemory_operation_error_total{operation="add",error_type="ProviderScopeRequiredError"} 1', prom)
        self.assertIn('agentmemory_event_total{event="memory_add.dedup_hit"} 1', prom)
        self.assertIn("agentmemory_operation_latency_seconds_bucket", prom)

    def test_record_llm_usage_computes_cost_for_known_model(self) -> None:
        registry = metrics_module._MetricsRegistry()
        registry.record_llm_usage(
            model="google/gemma-4-31b-it", prompt_tokens=1_000_000, completion_tokens=500_000
        )
        summary = registry.summary()
        usage = summary["usage"]["google/gemma-4-31b-it"]
        self.assertEqual(usage["prompt_tokens"], 1_000_000)
        self.assertEqual(usage["completion_tokens"], 500_000)
        # 1M prompt @ 0.15 + 0.5M completion @ 0.30 = 0.15 + 0.15 = 0.30 USD
        self.assertAlmostEqual(summary["total_estimated_cost_usd"], 0.30, places=4)

    def test_unknown_model_contributes_zero_cost_but_tokens_count(self) -> None:
        registry = metrics_module._MetricsRegistry()
        registry.record_llm_usage(model="novel/model", prompt_tokens=1_000_000, completion_tokens=0)
        summary = registry.summary()
        self.assertEqual(summary["usage"]["novel/model"]["prompt_tokens"], 1_000_000)
        self.assertEqual(summary["total_estimated_cost_usd"], 0)

    def test_timed_context_records_ok_on_success(self) -> None:
        # Point module-level record_operation at a fresh registry so this
        # test doesn't leak state across the suite.
        registry = metrics_module._MetricsRegistry()
        with mock.patch.object(metrics_module, "_REGISTRY", registry):
            with metrics_module.timed("probe"):
                time.sleep(0.002)
            snapshot = registry.operations_snapshot()
        self.assertEqual(snapshot["probe"].ok, 1)
        self.assertGreater(snapshot["probe"].latency_count, 0)

    def test_timed_context_records_error_and_reraises(self) -> None:
        registry = metrics_module._MetricsRegistry()
        with mock.patch.object(metrics_module, "_REGISTRY", registry):
            with self.assertRaises(RuntimeError):
                with metrics_module.timed("probe"):
                    raise RuntimeError("boom")
            errors = registry.errors_snapshot()
        self.assertEqual(errors[("probe", "RuntimeError")], 1)


class LifecycleTTLTests(unittest.TestCase):
    def test_resolve_expires_at_from_ttl_seconds(self) -> None:
        now = lifecycle_module.utc_now()
        resolved = lifecycle_module.resolve_expires_at({"ttl_seconds": 60})
        self.assertIsNotNone(resolved)
        parsed = lifecycle_module._parse_expires_at(resolved)
        self.assertIsNotNone(parsed)
        delta = parsed - now
        self.assertGreater(delta.total_seconds(), 50)
        self.assertLess(delta.total_seconds(), 120)

    def test_resolve_expires_at_explicit_iso_wins_over_ttl(self) -> None:
        resolved = lifecycle_module.resolve_expires_at(
            {"ttl_seconds": 60, "expires_at": "2030-01-01T00:00:00Z"}
        )
        self.assertIsNotNone(resolved)
        # Explicit value is preserved (normalized to UTC ISO with +00:00)
        self.assertTrue(resolved.startswith("2030-01-01"))

    def test_apply_expiry_drops_ttl_seconds_key(self) -> None:
        metadata = {"ttl_seconds": 120, "marker": "x"}
        cleaned = lifecycle_module.apply_expiry_to_metadata(metadata)
        self.assertNotIn("ttl_seconds", cleaned)
        self.assertIn("expires_at", cleaned)
        self.assertEqual(cleaned["marker"], "x")

    def test_apply_expiry_passthrough_without_expiry_keys(self) -> None:
        metadata = {"marker": "x"}
        cleaned = lifecycle_module.apply_expiry_to_metadata(metadata)
        self.assertEqual(cleaned, {"marker": "x"})

    def test_is_expired_past_and_future(self) -> None:
        now = lifecycle_module.utc_now()
        past = {"metadata": {"expires_at": (now - timedelta(seconds=1)).isoformat()}}
        future = {"metadata": {"expires_at": (now + timedelta(seconds=60)).isoformat()}}
        no_meta = {"memory": "ok"}
        self.assertTrue(lifecycle_module.is_expired(past, now=now))
        self.assertFalse(lifecycle_module.is_expired(future, now=now))
        self.assertFalse(lifecycle_module.is_expired(no_meta, now=now))

    def test_filter_unexpired_removes_past_records(self) -> None:
        now = lifecycle_module.utc_now()
        records = [
            {"id": "a", "metadata": {"expires_at": (now - timedelta(seconds=1)).isoformat()}},
            {"id": "b", "metadata": {"expires_at": (now + timedelta(seconds=60)).isoformat()}},
            {"id": "c", "metadata": {}},
        ]
        kept = lifecycle_module.filter_unexpired(records, now=now)
        self.assertEqual([r["id"] for r in kept], ["b", "c"])

    def test_list_filters_expired_on_read_path(self) -> None:
        now = lifecycle_module.utc_now()
        fresh = {"id": "a", "memory": "fresh", "metadata": {"expires_at": (now + timedelta(seconds=60)).isoformat()}}
        stale = {"id": "b", "memory": "stale", "metadata": {"expires_at": (now - timedelta(seconds=1)).isoformat()}}

        def fake_memory_list(**_kwargs):
            return [fresh, stale]

        with mock.patch.object(agentmemory_operations, "memory_list", fake_memory_list), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "localjson"), \
             mock.patch.object(agentmemory_operations, "active_provider_capabilities", lambda: _caps(requires_scope_for_list=False, supports_scopeless_list=True)):
            result = agentmemory_operations.OPERATIONS["list"].execute({"user_id": "u1"})
        self.assertEqual([r["id"] for r in result], ["a"])

    def test_list_refills_after_filtering_expired_records(self) -> None:
        now = lifecycle_module.utc_now()
        fresh_a = {"id": "a", "memory": "fresh-a", "metadata": {"expires_at": (now + timedelta(seconds=60)).isoformat()}}
        stale = {"id": "b", "memory": "stale", "metadata": {"expires_at": (now - timedelta(seconds=1)).isoformat()}}
        fresh_c = {"id": "c", "memory": "fresh-c", "metadata": {"expires_at": (now + timedelta(seconds=120)).isoformat()}}
        requested_limits: list[int] = []

        def fake_memory_list(**kwargs):
            requested_limits.append(kwargs["limit"])
            full = [fresh_a, stale, fresh_c]
            return full[: kwargs["limit"]]

        with mock.patch.object(agentmemory_operations, "memory_list", fake_memory_list), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "localjson"), \
             mock.patch.object(agentmemory_operations, "active_provider_capabilities", lambda: _caps(requires_scope_for_list=False, supports_scopeless_list=True)):
            result = agentmemory_operations.OPERATIONS["list"].execute({"limit": 2})

        self.assertEqual(requested_limits, [2, 4])
        self.assertEqual([r["id"] for r in result], ["a", "c"])

    def test_list_page_filters_expired_records(self) -> None:
        now = lifecycle_module.utc_now()
        fresh = {"id": "a", "memory": "fresh", "metadata": {"expires_at": (now + timedelta(seconds=60)).isoformat()}}
        stale = {"id": "b", "memory": "stale", "metadata": {"expires_at": (now - timedelta(seconds=1)).isoformat()}}

        def fake_memory_list_page(**_kwargs):
            return {
                "provider": "localjson",
                "items": [fresh, stale],
                "next_cursor": "next",
                "pagination_supported": True,
            }

        with mock.patch.object(agentmemory_operations, "memory_list_page", fake_memory_list_page), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "localjson"), \
             mock.patch.object(agentmemory_operations, "active_provider_capabilities", lambda: _caps(requires_scope_for_list=False, supports_scopeless_list=True, supports_pagination=True)):
            result = agentmemory_operations.OPERATIONS["list_page"].execute({"limit": 2})

        self.assertEqual([r["id"] for r in result["items"]], ["a"])
        self.assertEqual(result["next_cursor"], "next")

    def test_get_on_expired_raises_memory_not_found(self) -> None:
        from agentmemory.providers.base import MemoryNotFoundError
        now = lifecycle_module.utc_now()
        stale = {"id": "b", "memory": "stale", "metadata": {"expires_at": (now - timedelta(seconds=1)).isoformat()}}

        with mock.patch.object(agentmemory_operations, "memory_get", lambda _id: stale), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False):
            with self.assertRaises(MemoryNotFoundError):
                agentmemory_operations.OPERATIONS["get"].execute({"memory_id": "b"})

    def test_add_normalizes_ttl_before_calling_provider(self) -> None:
        captured = {}

        def fake_memory_add(**kwargs):
            captured.update(kwargs)
            return {"id": "m1", "memory": "ok", "provider": "fake"}

        with mock.patch.object(agentmemory_operations, "memory_add", fake_memory_add), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False):
            agentmemory_operations.OPERATIONS["add"].execute({
                "messages": [{"role": "user", "content": "hello"}],
                "text": "hello",
                "user_id": "u1",
                "metadata": {"ttl_seconds": 120, "marker": "x"},
            })
        self.assertIn("expires_at", captured["metadata"])
        self.assertNotIn("ttl_seconds", captured["metadata"])
        self.assertEqual(captured["metadata"]["marker"], "x")

    def test_search_refills_after_filtering_expired_records(self) -> None:
        now = lifecycle_module.utc_now()
        fresh_a = {"id": "a", "memory": "fresh-a", "score": 0.99, "metadata": {"expires_at": (now + timedelta(seconds=60)).isoformat()}}
        stale = {"id": "b", "memory": "stale", "score": 0.98, "metadata": {"expires_at": (now - timedelta(seconds=1)).isoformat()}}
        fresh_c = {"id": "c", "memory": "fresh-c", "score": 0.97, "metadata": {"expires_at": (now + timedelta(seconds=120)).isoformat()}}
        requested_limits: list[int] = []

        def fake_memory_search(**kwargs):
            requested_limits.append(kwargs["limit"])
            full = [fresh_a, stale, fresh_c]
            return full[: kwargs["limit"]]

        with mock.patch.object(agentmemory_operations, "memory_search", fake_memory_search), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "mem0"), \
             mock.patch.object(agentmemory_operations, "active_provider_capabilities", lambda: _caps()):
            result = agentmemory_operations.OPERATIONS["search"].execute({"query": "fresh", "user_id": "u1", "limit": 2})

        self.assertEqual(requested_limits, [2, 4])
        self.assertEqual([r["id"] for r in result], ["a", "c"])

    def test_search_page_filters_expired_records(self) -> None:
        now = lifecycle_module.utc_now()
        fresh = {"id": "a", "memory": "fresh-a", "score": 0.99, "metadata": {"expires_at": (now + timedelta(seconds=60)).isoformat()}}
        stale = {"id": "b", "memory": "stale", "score": 0.98, "metadata": {"expires_at": (now - timedelta(seconds=1)).isoformat()}}

        def fake_memory_search_page(**_kwargs):
            return {
                "provider": "localjson",
                "items": [fresh, stale],
                "next_cursor": "next",
                "pagination_supported": True,
            }

        with mock.patch.object(agentmemory_operations, "memory_search_page", fake_memory_search_page), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "localjson"), \
             mock.patch.object(agentmemory_operations, "active_provider_capabilities", lambda: _caps(requires_scope_for_search=False, supports_scopeless_list=True, supports_pagination=True)):
            result = agentmemory_operations.OPERATIONS["search_page"].execute({"query": "fresh", "limit": 2})

        self.assertEqual([r["id"] for r in result["items"]], ["a"])
        self.assertEqual(result["next_cursor"], "next")


class LifecycleDedupTests(unittest.TestCase):
    def test_dedup_hit_records_auxiliary_metric_without_insert(self) -> None:
        existing = {
            "id": "existing-id",
            "memory": "User deploys AgentMemory via Traefik on andrewm.ru",
            "score": 0.97,
            "provider": "mem0",
            "user_id": "u1",
        }
        registry = metrics_module._MetricsRegistry()

        with mock.patch.object(metrics_module, "_REGISTRY", registry), \
             mock.patch.object(agentmemory_operations, "memory_search", lambda **_: [existing]), \
             mock.patch.object(agentmemory_operations, "memory_add", lambda **_: self.fail("insert should not run")), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "mem0"), \
             mock.patch.object(agentmemory_operations, "active_provider_capabilities", lambda: _caps()):
            result = agentmemory_operations.OPERATIONS["add"].execute({
                "messages": [{"role": "user", "content": "User deploys AgentMemory via Traefik"}],
                "text": "User deploys AgentMemory via Traefik",
                "user_id": "u1",
                "dedup": True,
            })

        self.assertEqual(result["id"], "existing-id")
        summary = registry.summary()
        self.assertEqual(summary["operations"]["add"]["ok"], 1)
        self.assertEqual(summary["events"]["memory_add.dedup_hit"], 1)
        self.assertNotIn("memory_add.inserted", summary["events"])

    def test_dedup_probe_failure_records_warning_and_auxiliary_metric(self) -> None:
        registry = metrics_module._MetricsRegistry()

        def fake_memory_add(**_kwargs):
            return {"id": "new", "memory": "new text", "provider": "fake"}

        with mock.patch.object(metrics_module, "_REGISTRY", registry), \
             mock.patch.object(agentmemory_operations, "memory_search", side_effect=RuntimeError("search broke")), \
             mock.patch.object(agentmemory_operations, "memory_add", fake_memory_add), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "mem0"), \
             mock.patch.object(agentmemory_operations, "active_provider_capabilities", lambda: _caps()), \
             self.assertLogs(agentmemory_operations.LOGGER, level="WARNING") as logs:
            result = agentmemory_operations.OPERATIONS["add"].execute({
                "messages": [{"role": "user", "content": "new text"}],
                "text": "new text",
                "user_id": "u1",
                "dedup": True,
            })

        self.assertEqual(result["id"], "new")
        summary = registry.summary()
        self.assertEqual(summary["events"]["memory_add.dedup_probe_failed"], 1)
        self.assertEqual(summary["events"]["memory_add.inserted"], 1)
        self.assertTrue(any("memory_add dedup probe failed" in line for line in logs.output))

    def test_dedup_hit_returns_existing_record(self) -> None:
        existing = {
            "id": "existing-id",
            "memory": "User deploys AgentMemory via Traefik on andrewm.ru",
            "score": 0.97,
            "provider": "mem0",
            "user_id": "u1",
        }

        added = []

        def fake_memory_add(**kwargs):
            added.append(kwargs)
            return {"id": "should-not-happen", "memory": kwargs["messages"]}

        with mock.patch.object(agentmemory_operations, "memory_add", fake_memory_add), \
             mock.patch.object(agentmemory_operations, "memory_search", lambda **_: [existing]), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "mem0"), \
             mock.patch.object(agentmemory_operations, "active_provider_capabilities", lambda: _caps()):
            result = agentmemory_operations.OPERATIONS["add"].execute({
                "messages": [{"role": "user", "content": "User deploys AgentMemory via Traefik"}],
                "text": "User deploys AgentMemory via Traefik",
                "user_id": "u1",
                "dedup": True,
            })
        self.assertEqual(added, [])  # no insert happened
        self.assertEqual(result["id"], "existing-id")
        self.assertTrue(result["dedup_hit"])
        self.assertAlmostEqual(result["dedup_score"], 0.97)

    def test_dedup_miss_still_inserts(self) -> None:
        existing_weak = {"id": "weak", "memory": "unrelated", "score": 0.3, "provider": "mem0"}

        def fake_memory_add(**kwargs):
            return {"id": "new", "memory": "new text", "provider": "fake"}

        with mock.patch.object(agentmemory_operations, "memory_add", fake_memory_add), \
             mock.patch.object(agentmemory_operations, "memory_search", lambda **_: [existing_weak]), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "mem0"), \
             mock.patch.object(agentmemory_operations, "active_provider_capabilities", lambda: _caps()):
            result = agentmemory_operations.OPERATIONS["add"].execute({
                "messages": [{"role": "user", "content": "new text"}],
                "text": "new text",
                "user_id": "u1",
                "dedup": True,
            })
        self.assertEqual(result["id"], "new")
        self.assertNotIn("dedup_hit", result)

    def test_dedup_requires_scope(self) -> None:
        # Without a scope we skip dedup entirely (no search is run) and fall
        # through to the regular insert path.
        add_calls = []

        def fake_memory_add(**kwargs):
            add_calls.append(kwargs)
            return {"id": "new", "memory": "x", "provider": "fake"}

        def failing_memory_search(**_kwargs):
            raise AssertionError("dedup should not have issued a search without scope")

        with mock.patch.object(agentmemory_operations, "memory_add", fake_memory_add), \
             mock.patch.object(agentmemory_operations, "memory_search", failing_memory_search), \
             mock.patch.object(agentmemory_operations, "should_proxy_to_api", lambda: False), \
             mock.patch.object(agentmemory_operations, "active_provider_name", lambda: "mem0"), \
             mock.patch.object(agentmemory_operations, "active_provider_capabilities", lambda: _caps()):
            result = agentmemory_operations.OPERATIONS["add"].execute({
                "messages": [{"role": "user", "content": "x"}],
                "text": "x",
                "dedup": True,
            })
        self.assertEqual(len(add_calls), 1)
        self.assertEqual(result["id"], "new")


class LifecycleSweeperTests(unittest.TestCase):
    def test_run_sweep_once_prefers_registry_expired_ids_without_fixed_windows(self) -> None:
        def failing_list_scopes(**_kwargs):
            raise AssertionError("registry-backed sweeper should not walk scope windows")

        def failing_list_memories(**_kwargs):
            raise AssertionError("registry-backed sweeper should not walk memory windows")

        deleted_ids: list[str] = []

        def fake_delete(*, memory_id):
            deleted_ids.append(memory_id)

        result = lifecycle_module.run_sweep_once(
            list_scopes=failing_list_scopes,
            list_memories=failing_list_memories,
            delete_memory=fake_delete,
            list_expired_memory_ids=lambda: ["b", "b", "c"],
        )

        self.assertEqual(deleted_ids, ["b", "c"])
        self.assertEqual(result["deleted"], 2)
        self.assertEqual(result["swept"], 2)

    def test_run_sweep_once_deletes_only_expired(self) -> None:
        now = lifecycle_module.utc_now()
        fresh = {"id": "a", "metadata": {"expires_at": (now + timedelta(seconds=60)).isoformat()}}
        stale = {"id": "b", "metadata": {"expires_at": (now - timedelta(seconds=1)).isoformat()}}

        def fake_list_scopes(**_kwargs):
            return {"items": [{"kind": "user", "value": "u1"}]}

        def fake_list_memories(**_kwargs):
            return [fresh, stale]

        deleted_ids: list[str] = []

        def fake_delete(*, memory_id):
            deleted_ids.append(memory_id)

        result = lifecycle_module.run_sweep_once(
            list_scopes=fake_list_scopes,
            list_memories=fake_list_memories,
            delete_memory=fake_delete,
        )
        self.assertEqual(deleted_ids, ["b"])
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["swept"], 1)


if __name__ == "__main__":
    unittest.main()
