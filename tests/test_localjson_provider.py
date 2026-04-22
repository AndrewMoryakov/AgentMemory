import multiprocessing
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from agentmemory.providers.localjson import LocalJsonProvider
from agentmemory.runtime import scope_registry
from tests.provider_contract_harness import ProviderContractHarness


def _add_localjson_records(runtime_dir: str, storage_path: str, count: int, prefix: str) -> None:
    provider = LocalJsonProvider(
        runtime_config={"runtime_dir": runtime_dir},
        provider_config={"storage_path": storage_path, "default_limit": 100},
    )
    for index in range(count):
        provider.add_memory(messages=[{"role": "user", "content": f"{prefix}-{index}"}], user_id=prefix)


class LocalJsonProviderTests(ProviderContractHarness, unittest.TestCase):
    def create_provider(self, runtime_dir: str):
        return LocalJsonProvider(
            runtime_config={"runtime_dir": runtime_dir},
            provider_config=LocalJsonProvider.default_provider_config(runtime_dir=runtime_dir),
        )

    def test_localjson_capabilities_match_expected_behavior(self) -> None:
        capabilities = self.provider.capabilities()

        self.assertFalse(capabilities["supports_semantic_search"])
        self.assertTrue(capabilities["supports_text_search"])
        self.assertTrue(capabilities["supports_filters"])
        self.assertTrue(capabilities["supports_scopeless_list"])
        self.assertTrue(capabilities["supports_scope_inventory"])

    def test_list_scopes_returns_distinct_values_counts_and_filters(self) -> None:
        self.provider.add_memory(messages=[{"role": "user", "content": "one"}], user_id="default")
        self.provider.add_memory(messages=[{"role": "user", "content": "two"}], user_id="default", agent_id="writer")
        self.provider.add_memory(messages=[{"role": "user", "content": "three"}], run_id="run-42")

        inventory = self.provider.list_scopes()
        user_only = self.provider.list_scopes(kind="user")
        filtered = self.provider.list_scopes(query="def")

        self.assertEqual(inventory["totals"]["users"], 1)
        self.assertEqual(inventory["totals"]["agents"], 1)
        self.assertEqual(inventory["totals"]["runs"], 1)
        self.assertEqual(user_only["items"][0]["kind"], "user")
        self.assertEqual(user_only["items"][0]["value"], "default")
        self.assertEqual(user_only["items"][0]["count"], 2)
        self.assertEqual(len(filtered["items"]), 1)
        self.assertEqual(filtered["items"][0]["value"], "default")
        self.assertEqual(user_only["totals"]["agents"], 1)
        self.assertEqual(user_only["totals"]["runs"], 1)

    def test_list_scopes_orders_by_kind_count_value_and_honors_limit(self) -> None:
        self.provider.add_memory(messages=[{"role": "user", "content": "a"}], user_id="bravo")
        self.provider.add_memory(messages=[{"role": "user", "content": "b"}], user_id="alpha")
        self.provider.add_memory(messages=[{"role": "user", "content": "c"}], user_id="alpha")
        self.provider.add_memory(messages=[{"role": "user", "content": "d"}], agent_id="writer")
        self.provider.add_memory(messages=[{"role": "user", "content": "e"}], run_id="run-2")
        self.provider.add_memory(messages=[{"role": "user", "content": "f"}], run_id="run-1")

        inventory = self.provider.list_scopes(limit=3)

        self.assertEqual([item["kind"] for item in inventory["items"]], ["agent", "run", "run"])
        self.assertEqual([item["value"] for item in inventory["items"]], ["writer", "run-1", "run-2"])
        self.assertEqual(inventory["totals"], {"users": 2, "agents": 1, "runs": 2})

    def test_list_memories_page_walks_multiple_cursor_pages(self) -> None:
        created = [
            self.provider.add_memory(messages=[{"role": "user", "content": f"note {idx}"}], user_id="u1")
            for idx in range(3)
        ]

        first = self.provider.list_memories_page(user_id="u1", limit=2)
        second = self.provider.list_memories_page(user_id="u1", limit=2, cursor=first["next_cursor"])

        self.assertTrue(first["pagination_supported"])
        self.assertEqual(len(first["items"]), 2)
        self.assertIsNotNone(first["next_cursor"])
        self.assertEqual(len(second["items"]), 1)
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(
            {item["id"] for item in [*first["items"], *second["items"]]},
            {item["id"] for item in created},
        )

    def test_search_memory_page_walks_multiple_cursor_pages(self) -> None:
        created = [
            self.provider.add_memory(messages=[{"role": "user", "content": f"shared alpha note {idx}"}], user_id="u1")
            for idx in range(3)
        ]

        first = self.provider.search_memory_page(query="alpha", user_id="u1", limit=2, rerank=False)
        second = self.provider.search_memory_page(query="alpha", user_id="u1", limit=2, cursor=first["next_cursor"], rerank=False)

        self.assertTrue(first["pagination_supported"])
        self.assertEqual(len(first["items"]), 2)
        self.assertIsNotNone(first["next_cursor"])
        self.assertEqual(len(second["items"]), 1)
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(
            {item["id"] for item in [*first["items"], *second["items"]]},
            {item["id"] for item in created},
        )

    def test_concurrent_process_writes_preserve_all_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = f"{temp_dir}/localjson-memories.json"
            process_count = 2
            records_per_process = 3
            thread_env_keys = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
            original_env = {key: os.environ.get(key) for key in thread_env_keys}
            try:
                for key in thread_env_keys:
                    os.environ[key] = "1"
                processes = [
                    multiprocessing.Process(
                        target=_add_localjson_records,
                        args=(temp_dir, storage_path, records_per_process, f"worker-{index}"),
                    )
                    for index in range(process_count)
                ]

                for process in processes:
                    process.start()
                for process in processes:
                    process.join(10)

                for process in processes:
                    self.assertEqual(process.exitcode, 0)
            finally:
                for key, value in original_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

            provider = LocalJsonProvider(
                runtime_config={"runtime_dir": temp_dir},
                provider_config={"storage_path": storage_path, "default_limit": 100},
            )
            records = provider.list_memories(limit=100)

        self.assertEqual(len(records), process_count * records_per_process)

    def test_delete_memory_removes_scope_from_registry(self) -> None:
        created = self.provider.add_memory(messages=[{"role": "user", "content": "one"}], user_id="default")

        self.provider.delete_memory(memory_id=created["id"])
        inventory = self.provider.list_scopes()

        self.assertEqual(inventory["totals"], {"users": 0, "agents": 0, "runs": 0})

    def test_add_returns_success_when_registry_sync_fails(self) -> None:
        with mock.patch("agentmemory.providers.localjson.scope_registry.upsert_record", side_effect=sqlite3.OperationalError("boom")):
            created = self.provider.add_memory(messages=[{"role": "user", "content": "one"}], user_id="default")

        records = self.provider.list_memories(limit=10)
        status = scope_registry.scope_registry_status(self.provider.provider_name, self.provider.runtime_dir)

        self.assertEqual(created["memory"], "one")
        self.assertEqual(len(records), 1)
        self.assertEqual(status["status"], "needs_rebuild")
        self.assertEqual(status["last_failed_operation"], "add")

    def test_update_returns_success_when_registry_sync_fails(self) -> None:
        created = self.provider.add_memory(messages=[{"role": "user", "content": "one"}], user_id="default")

        with mock.patch("agentmemory.providers.localjson.scope_registry.upsert_record", side_effect=sqlite3.OperationalError("boom")):
            updated = self.provider.update_memory(memory_id=created["id"], data="two", metadata={"v": 2})

        fetched = self.provider.get_memory(created["id"])
        status = scope_registry.scope_registry_status(self.provider.provider_name, self.provider.runtime_dir)

        self.assertEqual(updated["memory"], "two")
        self.assertEqual(fetched["memory"], "two")
        self.assertEqual(status["status"], "needs_rebuild")
        self.assertEqual(status["last_failed_operation"], "update")

    def test_delete_returns_success_when_registry_sync_fails(self) -> None:
        created = self.provider.add_memory(messages=[{"role": "user", "content": "one"}], user_id="default")

        with mock.patch("agentmemory.providers.localjson.scope_registry.delete_record", side_effect=sqlite3.OperationalError("boom")):
            deleted = self.provider.delete_memory(memory_id=created["id"])

        status = scope_registry.scope_registry_status(self.provider.provider_name, self.provider.runtime_dir)

        self.assertTrue(deleted["deleted"])
        self.assertEqual(self.provider.list_memories(limit=10), [])
        self.assertEqual(status["status"], "needs_rebuild")
        self.assertEqual(status["last_failed_operation"], "delete")

    def test_successful_sync_clears_registry_degraded_state(self) -> None:
        scope_registry.mark_sync_failed(
            self.provider.provider_name,
            self.provider.runtime_dir,
            operation="add",
            memory_id="missing",
            error=sqlite3.OperationalError("boom"),
        )

        self.provider.add_memory(messages=[{"role": "user", "content": "one"}], user_id="default")
        status = scope_registry.scope_registry_status(self.provider.provider_name, self.provider.runtime_dir)

        self.assertEqual(status["status"], "ok")


if __name__ == "__main__":
    unittest.main()
