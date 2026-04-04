import tempfile
import unittest

from localjson_provider import LocalJsonProvider


class LocalJsonProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.provider = LocalJsonProvider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=LocalJsonProvider.default_provider_config(runtime_dir=self.temp_dir.name),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_add_and_get_memory(self) -> None:
        created = self.provider.add_memory(
            messages=[{"role": "user", "content": "prefers brutalist layouts"}],
            user_id="hopt",
            metadata={"topic": "design"},
        )

        fetched = self.provider.get_memory(created["id"])

        self.assertEqual(fetched["memory"], "prefers brutalist layouts")
        self.assertEqual(fetched["metadata"]["topic"], "design")

    def test_search_memory_returns_ranked_matches(self) -> None:
        self.provider.add_memory(messages=[{"role": "user", "content": "prefers brutalist layouts"}], user_id="hopt")
        self.provider.add_memory(messages=[{"role": "user", "content": "deploy target is local machine"}], user_id="hopt")

        results = self.provider.search_memory(query="brutalist", user_id="hopt", limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["memory"], "prefers brutalist layouts")
        self.assertGreaterEqual(results[0]["score"], 1.0)

    def test_update_and_delete_memory(self) -> None:
        created = self.provider.add_memory(messages=[{"role": "user", "content": "old text"}], user_id="hopt")

        updated = self.provider.update_memory(memory_id=created["id"], data="new text", metadata={"v": 2})
        deleted = self.provider.delete_memory(memory_id=created["id"])

        self.assertEqual(updated["memory"], "new text")
        self.assertEqual(updated["metadata"]["v"], 2)
        self.assertTrue(deleted["deleted"])


if __name__ == "__main__":
    unittest.main()
