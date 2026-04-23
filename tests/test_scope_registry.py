import multiprocessing
import tempfile
import unittest

from agentmemory.runtime import scope_registry


def _worker_upsert(runtime_dir: str, provider_name: str, index: int) -> None:
    scope_registry.upsert_record(
        provider_name,
        {
            "id": f"worker-{index}",
            "memory": f"record-{index}",
            "user_id": f"user-{index}",
            "created_at": "2026-04-22T10:00:00+00:00",
            "updated_at": "2026-04-22T10:00:00+00:00",
            "provider": provider_name,
        },
        runtime_dir,
    )


class ScopeRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runtime_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_list_inventory_preserves_order_filters_and_totals(self) -> None:
        scope_registry.replace_provider_records(
            "mem0",
            [
                {"id": "1", "memory": "a", "provider": "mem0", "user_id": "bravo", "updated_at": "2026-04-09T10:00:00+00:00"},
                {"id": "2", "memory": "b", "provider": "mem0", "user_id": "alpha", "updated_at": "2026-04-09T10:01:00+00:00"},
                {"id": "3", "memory": "c", "provider": "mem0", "user_id": "alpha", "updated_at": "2026-04-09T10:02:00+00:00"},
                {"id": "4", "memory": "d", "provider": "mem0", "agent_id": "writer", "updated_at": "2026-04-09T10:03:00+00:00"},
                {"id": "5", "memory": "e", "provider": "mem0", "run_id": "run-2", "updated_at": "2026-04-09T10:04:00+00:00"},
                {"id": "6", "memory": "f", "provider": "mem0", "run_id": "run-1", "updated_at": "2026-04-09T10:05:00+00:00"},
            ],
            self.runtime_dir,
        )

        inventory = scope_registry.list_inventory("mem0", 3, None, None, self.runtime_dir)
        filtered = scope_registry.list_inventory("mem0", 10, "user", "alp", self.runtime_dir)

        self.assertEqual([item["kind"] for item in inventory["items"]], ["agent", "run", "run"])
        self.assertEqual([item["value"] for item in inventory["items"]], ["writer", "run-1", "run-2"])
        self.assertEqual(inventory["totals"], {"users": 2, "agents": 1, "runs": 2})
        self.assertEqual(filtered["totals"], {"users": 1, "agents": 0, "runs": 0})
        self.assertEqual(filtered["items"][0]["value"], "alpha")

    def test_list_inventory_page_walks_with_opaque_cursor(self) -> None:
        scope_registry.replace_provider_records(
            "mem0",
            [
                {"id": "1", "memory": "a", "provider": "mem0", "user_id": "bravo"},
                {"id": "2", "memory": "b", "provider": "mem0", "user_id": "alpha"},
                {"id": "3", "memory": "c", "provider": "mem0", "user_id": "alpha"},
                {"id": "4", "memory": "d", "provider": "mem0", "agent_id": "writer"},
                {"id": "5", "memory": "e", "provider": "mem0", "run_id": "run-2"},
                {"id": "6", "memory": "f", "provider": "mem0", "run_id": "run-1"},
            ],
            self.runtime_dir,
        )

        first = scope_registry.list_inventory_page("mem0", limit=2, cursor=None, kind=None, query=None, runtime_dir=self.runtime_dir)
        second = scope_registry.list_inventory_page("mem0", limit=2, cursor=first["next_cursor"], kind=None, query=None, runtime_dir=self.runtime_dir)
        third = scope_registry.list_inventory_page("mem0", limit=2, cursor=second["next_cursor"], kind=None, query=None, runtime_dir=self.runtime_dir)

        values = [item["value"] for page in (first, second, third) for item in page["items"]]
        self.assertEqual(values, ["writer", "run-1", "run-2", "alpha", "bravo"])
        self.assertIsNotNone(first["next_cursor"])
        self.assertIsNotNone(second["next_cursor"])
        self.assertIsNone(third["next_cursor"])
        self.assertTrue(first["pagination_supported"])
        self.assertEqual(first["totals"], {"users": 2, "agents": 1, "runs": 2})

    def test_replace_provider_records_only_replaces_target_provider(self) -> None:
        scope_registry.replace_provider_records(
            "mem0",
            [{"id": "1", "memory": "a", "provider": "mem0", "user_id": "user-a"}],
            self.runtime_dir,
        )
        scope_registry.replace_provider_records(
            "localjson",
            [{"id": "2", "memory": "b", "provider": "localjson", "user_id": "user-b"}],
            self.runtime_dir,
        )
        scope_registry.replace_provider_records(
            "mem0",
            [{"id": "3", "memory": "c", "provider": "mem0", "agent_id": "agent-c"}],
            self.runtime_dir,
        )

        mem0_inventory = scope_registry.list_inventory("mem0", 10, None, None, self.runtime_dir)
        local_inventory = scope_registry.list_inventory("localjson", 10, None, None, self.runtime_dir)

        self.assertEqual(mem0_inventory["totals"], {"users": 0, "agents": 1, "runs": 0})
        self.assertEqual(local_inventory["totals"], {"users": 1, "agents": 0, "runs": 0})

    def test_list_expired_memory_ids_uses_registry_expiry_index(self) -> None:
        scope_registry.replace_provider_records(
            "mem0",
            [
                {
                    "id": "expired",
                    "memory": "a",
                    "provider": "mem0",
                    "user_id": "u1",
                    "metadata": {"expires_at": "2026-04-22T00:00:00+00:00"},
                },
                {
                    "id": "fresh",
                    "memory": "b",
                    "provider": "mem0",
                    "user_id": "u1",
                    "metadata": {"expires_at": "2026-04-24T00:00:00+00:00"},
                },
                {"id": "permanent", "memory": "c", "provider": "mem0", "user_id": "u1"},
            ],
            self.runtime_dir,
        )
        scope_registry.replace_provider_records(
            "localjson",
            [
                {
                    "id": "other-provider-expired",
                    "memory": "d",
                    "provider": "localjson",
                    "user_id": "u1",
                    "metadata": {"expires_at": "2026-04-22T00:00:00+00:00"},
                },
            ],
            self.runtime_dir,
        )

        expired = scope_registry.list_expired_memory_ids("mem0", self.runtime_dir)

        self.assertEqual(expired, ["expired"])

    def test_concurrent_upserts_preserve_all_records(self) -> None:
        processes = [
            multiprocessing.Process(target=_worker_upsert, args=(self.runtime_dir, "localjson", index))
            for index in range(4)
        ]

        for process in processes:
            process.start()
        for process in processes:
            process.join(10)

        for process in processes:
            self.assertEqual(process.exitcode, 0)

        inventory = scope_registry.list_inventory("localjson", 10, None, None, self.runtime_dir)

        self.assertEqual(inventory["totals"], {"users": 4, "agents": 0, "runs": 0})
