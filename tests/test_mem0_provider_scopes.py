import tempfile
import unittest

from agentmemory.providers.mem0 import Mem0Provider
from agentmemory.providers.base import ProviderUnavailableError, ProviderValidationError


class Mem0ProviderScopeInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.provider = Mem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_list_scopes_aggregates_user_agent_and_run_values(self) -> None:
        self.provider._iter_scope_payloads = lambda: [  # type: ignore[method-assign]
            {"user_id": "default", "updated_at": "2026-04-09T10:00:00+00:00"},
            {"user_id": "default", "agent_id": "writer", "created_at": "2026-04-09T09:00:00+00:00"},
            {"run_id": "run-42", "updated_at": "2026-04-09T11:00:00+00:00"},
        ]

        inventory = self.provider.list_scopes()
        users = [item for item in inventory["items"] if item["kind"] == "user"]

        self.assertEqual(inventory["provider"], "mem0")
        self.assertEqual(inventory["totals"], {"users": 1, "agents": 1, "runs": 1})
        self.assertEqual(users[0]["value"], "default")
        self.assertEqual(users[0]["count"], 2)

    def test_list_scopes_supports_kind_and_query_filters(self) -> None:
        self.provider._iter_scope_payloads = lambda: [  # type: ignore[method-assign]
            {"user_id": "default", "agent_id": "writer", "updated_at": "2026-04-09T10:00:00+00:00"},
            {"user_id": "other", "updated_at": "2026-04-09T10:05:00+00:00"},
        ]

        inventory = self.provider.list_scopes(kind="user", query="def")

        self.assertEqual(inventory["totals"]["users"], 1)
        self.assertEqual(inventory["totals"]["agents"], 0)
        self.assertEqual(inventory["totals"]["runs"], 0)
        self.assertEqual(len(inventory["items"]), 1)
        self.assertEqual(inventory["items"][0]["value"], "default")

    def test_list_scopes_rejects_invalid_kind(self) -> None:
        with self.assertRaises(ProviderValidationError):
            self.provider.list_scopes(kind="session")

    def test_list_scopes_surfaces_storage_unavailability(self) -> None:
        def fail():
            raise ProviderUnavailableError("storage unavailable")

        self.provider._iter_scope_payloads = fail  # type: ignore[method-assign]
        with self.assertRaises(ProviderUnavailableError):
            self.provider.list_scopes()

    def test_list_scopes_sorts_by_kind_count_value_and_applies_limit(self) -> None:
        self.provider._iter_scope_payloads = lambda: [  # type: ignore[method-assign]
            {"user_id": "bravo", "updated_at": "2026-04-09T10:00:00+00:00"},
            {"user_id": "alpha", "updated_at": "2026-04-09T10:01:00+00:00"},
            {"user_id": "alpha", "updated_at": "2026-04-09T10:02:00+00:00"},
            {"agent_id": "writer", "updated_at": "2026-04-09T10:03:00+00:00"},
            {"run_id": "run-2", "updated_at": "2026-04-09T10:04:00+00:00"},
            {"run_id": "run-1", "updated_at": "2026-04-09T10:05:00+00:00"},
        ]

        inventory = self.provider.list_scopes(limit=3)

        self.assertEqual([item["kind"] for item in inventory["items"]], ["agent", "run", "run"])
        self.assertEqual([item["value"] for item in inventory["items"]], ["writer", "run-1", "run-2"])
        self.assertEqual(inventory["totals"], {"users": 2, "agents": 1, "runs": 2})

    def test_list_scopes_uses_latest_timestamp_for_last_seen_at(self) -> None:
        self.provider._iter_scope_payloads = lambda: [  # type: ignore[method-assign]
            {"user_id": "default", "created_at": "2026-04-09T09:00:00+00:00"},
            {"user_id": "default", "updated_at": "2026-04-09T11:00:00+00:00"},
        ]

        inventory = self.provider.list_scopes(kind="user")

        self.assertEqual(inventory["items"][0]["last_seen_at"], "2026-04-09T11:00:00+00:00")
