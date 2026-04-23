import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

import agentmemory.runtime.admin as agentmemory_admin
import agentmemory.runtime.config as agentmemory_runtime
from agentmemory.runtime import lifecycle as lifecycle_module
from agentmemory.providers.base import ProviderCapabilityError


class AgentMemoryAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.original_config_path = agentmemory_runtime.CONFIG_PATH
        self.original_env_path = agentmemory_runtime.ENV_PATH

        agentmemory_runtime.CONFIG_PATH = base / "agentmemory.config.json"
        agentmemory_runtime.ENV_PATH = base / ".env"
        config = agentmemory_runtime.default_runtime_config()
        config["runtime"]["provider"] = "localjson"
        config["runtime"]["runtime_dir"] = self.temp_dir.name
        config["providers"]["localjson"] = agentmemory_runtime.provider_class("localjson").default_provider_config(
            runtime_dir=self.temp_dir.name
        )
        agentmemory_runtime.write_runtime_config(config)

    def tearDown(self) -> None:
        agentmemory_runtime.CONFIG_PATH = self.original_config_path
        agentmemory_runtime.ENV_PATH = self.original_env_path
        agentmemory_runtime.clear_caches()
        self.temp_dir.cleanup()

    def test_admin_list_and_pin_memory(self) -> None:
        created = agentmemory_runtime.memory_add(
            messages=[{"role": "user", "content": "prefers compact changelogs"}],
            user_id="demo",
            metadata={"topic": "docs"},
        )

        pinned = agentmemory_admin.pin_admin_memory(created["id"], pinned=True)
        listed = agentmemory_admin.list_admin_memories(limit=20)

        self.assertTrue(pinned["pinned"])
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], created["id"])
        self.assertTrue(listed[0]["pinned"])

    def test_admin_update_changes_memory_and_overlay(self) -> None:
        created = agentmemory_runtime.memory_add(
            messages=[{"role": "user", "content": "old memory"}],
            user_id="demo",
        )

        updated = agentmemory_admin.update_admin_memory(
            created["id"],
            memory="new memory",
            metadata={"kind": "rule"},
            pinned=True,
        )

        self.assertEqual(updated["display_text"], "new memory")
        self.assertEqual(updated["metadata"]["kind"], "rule")
        self.assertTrue(updated["pinned"])

    def test_admin_stats_reports_counts(self) -> None:
        agentmemory_runtime.memory_add(messages=[{"role": "user", "content": "first"}], user_id="demo")
        second = agentmemory_runtime.memory_add(messages=[{"role": "user", "content": "second"}], user_id="demo")
        agentmemory_admin.pin_admin_memory(second["id"], pinned=True)

        stats = agentmemory_admin.admin_stats(limit=20)

        self.assertEqual(stats["provider"], "localjson")
        self.assertEqual(stats["totals"]["memories"], 2)
        self.assertEqual(stats["totals"]["pinned"], 1)

    def test_admin_list_and_stats_filter_expired_memories(self) -> None:
        now = lifecycle_module.utc_now()
        agentmemory_runtime.memory_add(
            messages=[{"role": "user", "content": "fresh"}],
            user_id="demo",
            metadata={"expires_at": (now + timedelta(seconds=60)).isoformat()},
        )
        expired = agentmemory_runtime.memory_add(
            messages=[{"role": "user", "content": "expired"}],
            user_id="demo",
            metadata={"expires_at": (now - timedelta(seconds=1)).isoformat()},
        )
        self.assertIsInstance(expired["id"], str)

        listed = agentmemory_admin.list_admin_memories(limit=20)
        stats = agentmemory_admin.admin_stats(limit=20)

        self.assertEqual([item["display_text"] for item in listed], ["fresh"])
        self.assertEqual(stats["totals"]["memories"], 1)
        self.assertEqual(stats["totals"]["pinned"], 0)

    def test_admin_get_hides_expired_memory(self) -> None:
        expired = agentmemory_runtime.memory_add(
            messages=[{"role": "user", "content": "expired"}],
            user_id="demo",
            metadata={"expires_at": (lifecycle_module.utc_now() - timedelta(seconds=1)).isoformat()},
        )

        with self.assertRaises(KeyError):
            agentmemory_admin.get_admin_memory(expired["id"])

    def test_admin_update_rejects_provider_without_update_capability(self) -> None:
        capabilities = agentmemory_runtime.active_provider_capabilities()
        capabilities["supports_update"] = False

        with (
            mock.patch.object(agentmemory_admin, "active_provider_capabilities", return_value=capabilities),
            mock.patch.object(agentmemory_admin, "memory_update", side_effect=AssertionError("should not update")),
        ):
            with self.assertRaises(ProviderCapabilityError):
                agentmemory_admin.update_admin_memory("missing", memory="new")

    def test_admin_delete_rejects_provider_without_delete_capability(self) -> None:
        capabilities = agentmemory_runtime.active_provider_capabilities()
        capabilities["supports_delete"] = False

        with (
            mock.patch.object(agentmemory_admin, "active_provider_capabilities", return_value=capabilities),
            mock.patch.object(agentmemory_admin, "memory_delete", side_effect=AssertionError("should not delete")),
        ):
            with self.assertRaises(ProviderCapabilityError):
                agentmemory_admin.delete_admin_memory("missing")


if __name__ == "__main__":
    unittest.main()
