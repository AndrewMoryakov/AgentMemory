import unittest

from agentmemory.runtime import reconcile


class AgentMemoryReconcileTests(unittest.TestCase):
    def test_find_conflicts_detects_opposite_polarity(self) -> None:
        records = [
            {"id": "a", "memory": "User likes tea", "metadata": {}, "user_id": "u1"},
            {"id": "b", "memory": "User does not like tea", "metadata": {}, "user_id": "u1"},
        ]

        conflicts = reconcile.find_conflicts(records)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["reason"], "opposite_polarity")
        self.assertEqual(conflicts[0]["left"]["id"], "a")
        self.assertEqual(conflicts[0]["right"]["id"], "b")

    def test_find_conflicts_detects_different_values_for_same_claim(self) -> None:
        records = [
            {"id": "a", "memory": "User prefers tea", "metadata": {}, "user_id": "u1"},
            {"id": "b", "memory": "User prefers coffee", "metadata": {}, "user_id": "u1"},
        ]

        conflicts = reconcile.find_conflicts(records)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["reason"], "different_values_for_same_claim")
        self.assertEqual(conflicts[0]["subject"], "user")
        self.assertEqual(conflicts[0]["predicate"], "prefers")

    def test_find_conflicts_can_use_structured_claim_metadata(self) -> None:
        records = [
            {
                "id": "a",
                "memory": "legacy phrasing",
                "metadata": {"claim_key": "user timezone", "claim_value": "UTC"},
                "user_id": "u1",
            },
            {
                "id": "b",
                "memory": "different phrasing",
                "metadata": {"claim_key": "user timezone", "claim_value": "Asia/Irkutsk"},
                "user_id": "u1",
            },
        ]

        conflicts = reconcile.find_conflicts(records)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["predicate"], "metadata_claim")


if __name__ == "__main__":
    unittest.main()
