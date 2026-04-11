import tempfile
from abc import ABC, abstractmethod

from agentmemory.providers.base import MemoryNotFoundError, ProviderCapabilityError


class ProviderContractHarness(ABC):
    required_record_fields = {
        "id",
        "memory",
        "metadata",
        "user_id",
        "agent_id",
        "run_id",
        "memory_type",
        "created_at",
        "updated_at",
        "provider",
    }

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.provider = self.create_provider(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @abstractmethod
    def create_provider(self, runtime_dir: str):
        raise NotImplementedError

    def default_scope(self) -> dict[str, str]:
        return {"user_id": "contract-user"}

    def make_messages(self, text: str) -> list[dict[str, str]]:
        return [{"role": "user", "content": text}]

    def create_memory(self, text: str, *, metadata=None):
        return self.provider.add_memory(
            messages=self.make_messages(text),
            metadata=metadata,
            **self.default_scope(),
        )

    def search_kwargs(self) -> dict[str, object]:
        capabilities = self.provider.capabilities()
        kwargs: dict[str, object] = {**self.default_scope(), "limit": 5}
        kwargs["rerank"] = True if capabilities["supports_rerank"] else False
        return kwargs

    def assert_record_shape(self, record, *, search_result: bool = False) -> None:
        self.assertTrue(self.required_record_fields.issubset(set(record.keys())))
        self.assertEqual(record["provider"], self.provider.provider_name)
        self.assertIsInstance(record["metadata"], dict)
        if search_result:
            self.assertIn("score", record)
        else:
            self.assertNotIn("score", record)

    def test_add_and_get_memory_follow_contract(self) -> None:
        created = self.create_memory("prefers brutalist layouts", metadata={"topic": "design"})
        fetched = self.provider.get_memory(created["id"])

        self.assert_record_shape(created)
        self.assert_record_shape(fetched)
        self.assertEqual(fetched["memory"], "prefers brutalist layouts")
        self.assertEqual(fetched["metadata"]["topic"], "design")

    def test_search_returns_ranked_contract_records(self) -> None:
        self.create_memory("prefers brutalist layouts")
        self.create_memory("deploy target is local machine")

        results = self.provider.search_memory(query="brutalist", **self.search_kwargs())

        self.assertEqual(len(results), 1)
        self.assert_record_shape(results[0], search_result=True)
        self.assertEqual(results[0]["memory"], "prefers brutalist layouts")
        self.assertGreaterEqual(results[0]["score"], 1.0)

    def test_update_and_delete_follow_contract(self) -> None:
        created = self.create_memory("old text")

        updated = self.provider.update_memory(memory_id=created["id"], data="new text", metadata={"v": 2})
        deleted = self.provider.delete_memory(memory_id=created["id"])

        self.assert_record_shape(updated)
        self.assertEqual(updated["memory"], "new text")
        self.assertEqual(updated["metadata"]["v"], 2)
        self.assertTrue(deleted["deleted"])
        self.assertEqual(deleted["provider"], self.provider.provider_name)

    def test_capabilities_expose_v1_shape(self) -> None:
        capabilities = self.provider.capabilities()

        expected_keys = {
            "supports_semantic_search",
            "supports_text_search",
            "supports_filters",
            "supports_metadata_filters",
            "supports_rerank",
            "supports_update",
            "supports_delete",
            "supports_scopeless_list",
            "requires_scope_for_list",
            "requires_scope_for_search",
            "supports_owner_process_mode",
            "supports_scope_inventory",
        }
        self.assertEqual(set(capabilities.keys()), expected_keys)

    def test_runtime_policy_exposes_transport_mode_contract(self) -> None:
        runtime_policy = self.provider.runtime_policy()

        self.assertEqual(set(runtime_policy.keys()), {"transport_mode"})
        self.assertIn(runtime_policy["transport_mode"], {"direct", "owner_process_proxy", "remote_only"})

    def test_list_scopes_returns_canonical_inventory_shape(self) -> None:
        self.create_memory("prefers brutalist layouts")
        inventory = self.provider.list_scopes()

        self.assertEqual(inventory["provider"], self.provider.provider_name)
        self.assertIn("items", inventory)
        self.assertIn("totals", inventory)
        self.assertEqual(set(inventory["totals"].keys()), {"users", "agents", "runs"})

    def test_missing_record_operations_raise_memory_not_found(self) -> None:
        with self.assertRaises(MemoryNotFoundError):
            self.provider.get_memory("missing")

        with self.assertRaises(MemoryNotFoundError):
            self.provider.update_memory(memory_id="missing", data="new")

        with self.assertRaises(MemoryNotFoundError):
            self.provider.delete_memory(memory_id="missing")

    def test_unsupported_rerank_raises_capability_error_when_declared(self) -> None:
        capabilities = self.provider.capabilities()
        if capabilities["supports_rerank"]:
            self.skipTest("provider supports rerank")

        with self.assertRaises(ProviderCapabilityError):
            self.provider.search_memory(query="demo", **self.default_scope(), rerank=True)
