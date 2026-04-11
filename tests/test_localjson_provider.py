import unittest

from agentmemory.providers.localjson import LocalJsonProvider
from tests.provider_contract_harness import ProviderContractHarness


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


if __name__ == "__main__":
    unittest.main()
