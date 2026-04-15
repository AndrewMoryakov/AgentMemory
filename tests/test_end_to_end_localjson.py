import tempfile
import unittest

from agentmemory.providers.localjson import LocalJsonProvider
from agentmemory.providers.base import MemoryNotFoundError


class EndToEndLocalJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.provider = LocalJsonProvider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=LocalJsonProvider.default_provider_config(runtime_dir=self.temp_dir.name),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _msg(self, text: str) -> list[dict[str, str]]:
        return [{"role": "user", "content": text}]

    def test_full_lifecycle_add_search_get_update_delete(self) -> None:
        created = self.provider.add_memory(
            messages=self._msg("prefers dark mode"),
            user_id="alice",
            metadata={"topic": "ui"},
        )
        self.assertIn("id", created)
        self.assertEqual(created["memory"], "prefers dark mode")
        self.assertEqual(created["user_id"], "alice")
        self.assertEqual(created["metadata"]["topic"], "ui")

        results = self.provider.search_memory(
            query="dark mode",
            user_id="alice",
            rerank=False,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], created["id"])
        self.assertIn("score", results[0])

        fetched = self.provider.get_memory(created["id"])
        self.assertEqual(fetched["id"], created["id"])
        self.assertEqual(fetched["memory"], "prefers dark mode")

        updated = self.provider.update_memory(
            memory_id=created["id"],
            data="prefers light mode",
            metadata={"topic": "ui", "updated": True},
        )
        self.assertEqual(updated["memory"], "prefers light mode")
        self.assertTrue(updated["metadata"]["updated"])

        fetched_again = self.provider.get_memory(created["id"])
        self.assertEqual(fetched_again["memory"], "prefers light mode")

        delete_result = self.provider.delete_memory(memory_id=created["id"])
        self.assertTrue(delete_result["deleted"])
        self.assertEqual(delete_result["id"], created["id"])

        with self.assertRaises(MemoryNotFoundError):
            self.provider.get_memory(created["id"])

    def test_multi_scope_isolation(self) -> None:
        self.provider.add_memory(messages=self._msg("alice note"), user_id="alice")
        self.provider.add_memory(messages=self._msg("bob note"), user_id="bob")
        self.provider.add_memory(messages=self._msg("agent note"), agent_id="agent-1")

        alice_memories = self.provider.list_memories(user_id="alice")
        bob_memories = self.provider.list_memories(user_id="bob")
        agent_memories = self.provider.list_memories(agent_id="agent-1")
        all_memories = self.provider.list_memories()

        self.assertEqual(len(alice_memories), 1)
        self.assertEqual(alice_memories[0]["memory"], "alice note")
        self.assertEqual(len(bob_memories), 1)
        self.assertEqual(bob_memories[0]["memory"], "bob note")
        self.assertEqual(len(agent_memories), 1)
        self.assertEqual(agent_memories[0]["memory"], "agent note")
        self.assertEqual(len(all_memories), 3)

    def test_search_with_filters(self) -> None:
        self.provider.add_memory(
            messages=self._msg("design preference"),
            user_id="alice",
            metadata={"topic": "design"},
        )
        self.provider.add_memory(
            messages=self._msg("code preference"),
            user_id="alice",
            metadata={"topic": "code"},
        )

        results = self.provider.search_memory(
            query="preference",
            user_id="alice",
            filters={"topic": "design"},
            rerank=False,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"]["topic"], "design")

    def test_list_with_limit(self) -> None:
        for i in range(5):
            self.provider.add_memory(messages=self._msg(f"note {i}"), user_id="u1")

        limited = self.provider.list_memories(user_id="u1", limit=3)
        all_items = self.provider.list_memories(user_id="u1")

        self.assertEqual(len(limited), 3)
        self.assertEqual(len(all_items), 5)

    def test_search_no_results_returns_empty_list(self) -> None:
        self.provider.add_memory(messages=self._msg("hello world"), user_id="u1")

        results = self.provider.search_memory(query="zzzznonexistent", user_id="u1", rerank=False)

        self.assertEqual(results, [])

    def test_scope_inventory_reflects_stored_memories(self) -> None:
        self.provider.add_memory(messages=self._msg("a"), user_id="alice")
        self.provider.add_memory(messages=self._msg("b"), user_id="alice", agent_id="writer")
        self.provider.add_memory(messages=self._msg("c"), run_id="run-1")

        inventory = self.provider.list_scopes()

        self.assertEqual(inventory["totals"]["users"], 1)
        self.assertEqual(inventory["totals"]["agents"], 1)
        self.assertEqual(inventory["totals"]["runs"], 1)

        user_scopes = self.provider.list_scopes(kind="user")
        self.assertEqual(len(user_scopes["items"]), 1)
        self.assertEqual(user_scopes["items"][0]["value"], "alice")
        self.assertEqual(user_scopes["items"][0]["count"], 2)


if __name__ == "__main__":
    unittest.main()
