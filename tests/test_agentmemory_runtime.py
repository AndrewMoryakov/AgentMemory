import json
import importlib.util
import os
import io
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

import agentmemory.runtime.config as agentmemory_runtime
from agentmemory.runtime import scope_registry


class AgentMemoryRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)

        self.original_config_path = agentmemory_runtime.CONFIG_PATH
        self.original_env_path = agentmemory_runtime.ENV_PATH

        agentmemory_runtime.CONFIG_PATH = base / "agentmemory.config.json"
        agentmemory_runtime.ENV_PATH = base / ".env"
        agentmemory_runtime.clear_caches()

    def tearDown(self) -> None:
        agentmemory_runtime.CONFIG_PATH = self.original_config_path
        agentmemory_runtime.ENV_PATH = self.original_env_path
        agentmemory_runtime.clear_caches()
        self.temp_dir.cleanup()

    def test_default_runtime_config_is_used_when_file_is_missing(self) -> None:
        config, source, path = agentmemory_runtime.load_runtime_config_with_source()

        self.assertEqual(source, "default")
        self.assertEqual(path, agentmemory_runtime.CONFIG_PATH)
        self.assertEqual(config["runtime"]["provider"], "mem0")

    def test_module_can_be_imported_with_missing_config_file(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "agentmemory_runtime_import_probe",
            Path(agentmemory_runtime.__file__),
        )
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None
        assert spec.loader is not None
        spec.loader.exec_module(module)

        self.assertEqual(module.default_runtime_config()["runtime"]["provider"], "mem0")

    def test_runtime_info_reports_provider_and_config_source(self) -> None:
        generic = agentmemory_runtime.default_runtime_config()
        agentmemory_runtime.write_runtime_config(generic)

        payload = agentmemory_runtime.runtime_info()

        self.assertEqual(payload["provider"], "mem0")
        self.assertEqual(payload["active_profile"], "default")
        self.assertEqual(payload["config_source"], "generic")
        self.assertIn("capabilities", payload)
        self.assertIn("runtime_policy", payload)
        self.assertIn("provider_contract", payload)
        self.assertIn("api_runtime", payload)
        self.assertEqual(payload["runtime_policy"]["transport_mode"], "owner_process_proxy")
        self.assertIn("llm_model", payload)
        self.assertIn("embedding_model", payload)

    def test_health_reports_provider_and_ok(self) -> None:
        generic = agentmemory_runtime.default_runtime_config()
        agentmemory_runtime.write_runtime_config(generic)

        payload = agentmemory_runtime.health()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["provider"], "mem0")
        self.assertEqual(payload["config_source"], "generic")
        self.assertEqual(payload["runtime_policy"]["transport_mode"], "owner_process_proxy")

    def test_write_runtime_config_writes_json_file(self) -> None:
        generic = agentmemory_runtime.default_runtime_config()
        agentmemory_runtime.write_runtime_config(generic)

        raw = agentmemory_runtime.CONFIG_PATH.read_text(encoding="ascii")
        decoded = json.loads(raw)
        self.assertEqual(decoded["active_profile"], "default")
        self.assertEqual(decoded["profiles"]["default"]["runtime"]["provider"], "mem0")

    def test_ensure_default_runtime_config_creates_generic_config(self) -> None:
        payload = agentmemory_runtime.ensure_default_runtime_config()

        self.assertEqual(payload["runtime"]["provider"], "mem0")
        self.assertTrue(agentmemory_runtime.CONFIG_PATH.exists())

    def test_provider_class_exposes_provider_specific_configuration_hooks(self) -> None:
        provider_type = agentmemory_runtime.provider_class("mem0")
        provider_config = provider_type.default_provider_config(runtime_dir="C:\\runtime")
        args = SimpleNamespace(
            openrouter_api_key="sk-test",
            openrouter_api_key_stdin=False,
            openrouter_api_key_env=None,
            llm_model="custom-llm",
            embedding_model=None,
            embedding_dims=2048,
            collection_name=None,
            site_url=None,
            app_name=None,
        )

        changed = provider_type.apply_cli_configuration(provider_config=provider_config, args=args)
        env_updates = provider_type.env_updates_from_args(args)

        self.assertTrue(changed)
        self.assertEqual(provider_config["llm"]["config"]["model"], "custom-llm")
        self.assertEqual(provider_config["embedder"]["config"]["embedding_dims"], 2048)
        self.assertEqual(env_updates["OPENROUTER_API_KEY"], "sk-test")

    def test_mem0_provider_reads_openrouter_key_from_stdin(self) -> None:
        provider_type = agentmemory_runtime.provider_class("mem0")
        args = SimpleNamespace(
            openrouter_api_key=None,
            openrouter_api_key_stdin=True,
            openrouter_api_key_env=None,
        )

        with mock.patch("agentmemory.providers.mem0.sys.stdin", io.StringIO("sk-from-stdin\n")):
            env_updates = provider_type.env_updates_from_args(args)

        self.assertEqual(env_updates["OPENROUTER_API_KEY"], "sk-from-stdin")

    def test_mem0_provider_reads_openrouter_key_from_named_env(self) -> None:
        provider_type = agentmemory_runtime.provider_class("mem0")
        args = SimpleNamespace(
            openrouter_api_key=None,
            openrouter_api_key_stdin=False,
            openrouter_api_key_env="AGENTMEMORY_TEST_OPENROUTER_KEY",
        )
        original = os.environ.get("AGENTMEMORY_TEST_OPENROUTER_KEY")
        try:
            os.environ["AGENTMEMORY_TEST_OPENROUTER_KEY"] = "sk-from-env"
            env_updates = provider_type.env_updates_from_args(args)
        finally:
            if original is None:
                os.environ.pop("AGENTMEMORY_TEST_OPENROUTER_KEY", None)
            else:
                os.environ["AGENTMEMORY_TEST_OPENROUTER_KEY"] = original

        self.assertEqual(env_updates["OPENROUTER_API_KEY"], "sk-from-env")

    def test_provider_registry_contains_second_test_provider(self) -> None:
        self.assertIn("localjson", agentmemory_runtime.provider_registry())
        self.assertIn("mem0", agentmemory_runtime.provider_registry())
        self.assertIn("claude_memory", agentmemory_runtime.provider_registry())

    def test_provider_class_exposes_certification_metadata(self) -> None:
        metadata = agentmemory_runtime.provider_class("mem0").provider_metadata()

        self.assertEqual(metadata["provider_name"], "mem0")
        self.assertEqual(metadata["certification_status"], "certified")
        self.assertEqual(metadata["expected_certification_status_code"], "certified_with_skips")

    def test_runtime_can_use_localjson_provider(self) -> None:
        config = agentmemory_runtime.default_runtime_config()
        config["runtime"]["provider"] = "localjson"
        config["providers"]["localjson"] = agentmemory_runtime.provider_class("localjson").default_provider_config(
            runtime_dir=self.temp_dir.name
        )
        agentmemory_runtime.write_runtime_config(config)

        payload = agentmemory_runtime.health()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["provider"], "localjson")
        self.assertIn("storage_path", payload)
        self.assertTrue(payload["capabilities"]["supports_text_search"])
        self.assertEqual(payload["runtime_policy"]["transport_mode"], "direct")

    def test_runtime_can_use_claude_memory_provider(self) -> None:
        project_root = Path(self.temp_dir.name) / "project"
        project_root.mkdir(parents=True, exist_ok=True)
        (project_root / ".git").mkdir(exist_ok=True)
        (project_root / "CLAUDE.md").write_text("# Root\n\nProject memory.\n", encoding="utf-8")
        user_claude_dir = Path(self.temp_dir.name) / "user-claude"
        auto_memory_dir = Path(self.temp_dir.name) / "auto-memory"
        config = agentmemory_runtime.default_runtime_config()
        config["runtime"]["provider"] = "claude_memory"
        config["providers"]["claude_memory"] = agentmemory_runtime.provider_class("claude_memory").default_provider_config(
            runtime_dir=self.temp_dir.name
        )
        config["providers"]["claude_memory"].update(
            {
                "project_root": str(project_root),
                "user_claude_dir": str(user_claude_dir),
                "auto_memory_dir": str(auto_memory_dir),
                "include_user_memory": False,
                "include_auto_memory": False,
                "agentmemory_write_dir": str(project_root / ".claude" / "rules" / "agentmemory"),
            }
        )
        agentmemory_runtime.write_runtime_config(config)

        payload = agentmemory_runtime.health()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["provider"], "claude_memory")
        self.assertEqual(payload["project_root"], str(project_root.resolve()))
        self.assertTrue(payload["capabilities"]["supports_text_search"])
        self.assertFalse(payload["capabilities"]["supports_scope_inventory"])
        self.assertEqual(payload["runtime_policy"]["transport_mode"], "direct")

    def test_runtime_info_uses_updated_api_host_and_port(self) -> None:
        config = agentmemory_runtime.default_runtime_config()
        config["runtime"]["api_host"] = "0.0.0.0"
        config["runtime"]["api_port"] = 9876
        agentmemory_runtime.write_runtime_config(config)

        payload = agentmemory_runtime.runtime_info()

        self.assertEqual(payload["api_host"], "0.0.0.0")
        self.assertEqual(payload["api_port"], 9876)

    def test_active_provider_capabilities_match_runtime_info(self) -> None:
        config = agentmemory_runtime.default_runtime_config()
        config["runtime"]["provider"] = "localjson"
        config["providers"]["localjson"] = agentmemory_runtime.provider_class("localjson").default_provider_config(
            runtime_dir=self.temp_dir.name
        )
        agentmemory_runtime.write_runtime_config(config)

        self.assertEqual(agentmemory_runtime.active_provider_capabilities(), agentmemory_runtime.runtime_info()["capabilities"])

    def test_active_provider_runtime_policy_matches_runtime_info(self) -> None:
        config = agentmemory_runtime.default_runtime_config()
        config["runtime"]["provider"] = "localjson"
        config["providers"]["localjson"] = agentmemory_runtime.provider_class("localjson").default_provider_config(
            runtime_dir=self.temp_dir.name
        )
        agentmemory_runtime.write_runtime_config(config)

        self.assertEqual(agentmemory_runtime.active_provider_runtime_policy(), agentmemory_runtime.runtime_info()["runtime_policy"])

    def test_active_provider_runtime_policy_invalidates_when_config_file_changes_on_disk(self) -> None:
        initial = agentmemory_runtime.default_runtime_config()
        agentmemory_runtime.write_runtime_config(initial)

        first_policy = agentmemory_runtime.active_provider_runtime_policy()

        updated_document = agentmemory_runtime.default_runtime_document()
        updated_document["profiles"]["default"]["runtime"]["provider"] = "localjson"
        updated_document["profiles"]["default"]["providers"]["localjson"] = (
            agentmemory_runtime.provider_class("localjson").default_provider_config(runtime_dir=self.temp_dir.name)
        )
        updated_document["profiles"]["default"]["providers"].pop("mem0", None)
        agentmemory_runtime.CONFIG_PATH.write_text(json.dumps(updated_document, ensure_ascii=True), encoding="ascii")

        second_policy = agentmemory_runtime.active_provider_runtime_policy()

        self.assertEqual(first_policy["transport_mode"], "owner_process_proxy")
        self.assertEqual(second_policy["transport_mode"], "direct")

    def test_active_provider_capabilities_invalidates_when_config_file_changes_on_disk(self) -> None:
        initial = agentmemory_runtime.default_runtime_config()
        agentmemory_runtime.write_runtime_config(initial)

        first_capabilities = agentmemory_runtime.active_provider_capabilities()

        updated_document = agentmemory_runtime.default_runtime_document()
        updated_document["profiles"]["default"]["runtime"]["provider"] = "localjson"
        updated_document["profiles"]["default"]["providers"]["localjson"] = (
            agentmemory_runtime.provider_class("localjson").default_provider_config(runtime_dir=self.temp_dir.name)
        )
        updated_document["profiles"]["default"]["providers"].pop("mem0", None)
        agentmemory_runtime.CONFIG_PATH.write_text(json.dumps(updated_document, ensure_ascii=True), encoding="ascii")

        second_capabilities = agentmemory_runtime.active_provider_capabilities()

        self.assertTrue(first_capabilities["supports_owner_process_mode"])
        self.assertFalse(second_capabilities["supports_owner_process_mode"])

    def test_memory_list_scopes_uses_active_provider(self) -> None:
        config = agentmemory_runtime.default_runtime_config()
        config["runtime"]["provider"] = "localjson"
        config["runtime"]["runtime_dir"] = self.temp_dir.name
        config["providers"]["localjson"] = agentmemory_runtime.provider_class("localjson").default_provider_config(
            runtime_dir=self.temp_dir.name
        )
        agentmemory_runtime.write_runtime_config(config)

        agentmemory_runtime.memory_add(messages=[{"role": "user", "content": "hello"}], user_id="default")
        payload = agentmemory_runtime.memory_list_scopes()

        self.assertEqual(payload["provider"], "localjson")
        self.assertEqual(payload["totals"]["users"], 1)

    def test_runtime_info_includes_scope_registry_status(self) -> None:
        config = agentmemory_runtime.default_runtime_config()
        config["runtime"]["provider"] = "localjson"
        config["runtime"]["runtime_dir"] = self.temp_dir.name
        config["providers"]["localjson"] = agentmemory_runtime.provider_class("localjson").default_provider_config(
            runtime_dir=self.temp_dir.name
        )
        agentmemory_runtime.write_runtime_config(config)

        scope_registry.mark_sync_failed(
            "localjson",
            self.temp_dir.name,
            operation="add",
            memory_id="missing",
            error=RuntimeError("boom"),
        )
        payload = agentmemory_runtime.runtime_info()

        self.assertIn("scope_registry", payload)
        self.assertEqual(payload["scope_registry"]["status"], "needs_rebuild")

    def test_rebuild_scope_registry_clears_degraded_status_and_returns_status(self) -> None:
        config = agentmemory_runtime.default_runtime_config()
        config["runtime"]["provider"] = "localjson"
        config["runtime"]["runtime_dir"] = self.temp_dir.name
        config["providers"]["localjson"] = agentmemory_runtime.provider_class("localjson").default_provider_config(
            runtime_dir=self.temp_dir.name
        )
        agentmemory_runtime.write_runtime_config(config)

        agentmemory_runtime.memory_add(messages=[{"role": "user", "content": "hello"}], user_id="default")
        scope_registry.mark_sync_failed(
            "localjson",
            self.temp_dir.name,
            operation="add",
            memory_id="missing",
            error=RuntimeError("boom"),
        )

        payload = agentmemory_runtime.rebuild_scope_registry()

        self.assertEqual(payload["provider"], "localjson")
        self.assertEqual(payload["scope_registry"]["status"], "ok")
        self.assertIsNotNone(payload["scope_registry"]["last_rebuild_at"])

    def test_profile_document_supports_create_and_switch(self) -> None:
        generic = agentmemory_runtime.default_runtime_config()
        agentmemory_runtime.write_runtime_config(generic)

        created = agentmemory_runtime.create_profile("staging")
        self.assertEqual(created["runtime"]["runtime_dir"], str(agentmemory_runtime.RUNTIME_DIR / "staging"))

        agentmemory_runtime.set_active_profile("staging")
        payload = agentmemory_runtime.runtime_info()

        self.assertEqual(payload["active_profile"], "staging")
        self.assertIn("staging", payload["profiles"])

    def test_provider_contract_matches_runtime_info(self) -> None:
        generic = agentmemory_runtime.default_runtime_config()
        generic["runtime"]["provider"] = "localjson"
        generic["providers"]["localjson"] = agentmemory_runtime.provider_class("localjson").default_provider_config(
            runtime_dir=self.temp_dir.name
        )
        agentmemory_runtime.write_runtime_config(generic)

        self.assertEqual(agentmemory_runtime.active_provider_contract(), agentmemory_runtime.runtime_info()["provider_contract"])

    def test_api_runtime_diagnostics_reports_available_when_port_is_free(self) -> None:
        generic = agentmemory_runtime.default_runtime_config()
        generic["runtime"]["provider"] = "localjson"
        generic["providers"]["localjson"] = agentmemory_runtime.provider_class("localjson").default_provider_config(
            runtime_dir=self.temp_dir.name
        )
        agentmemory_runtime.write_runtime_config(generic)
        original_read_api_pid = agentmemory_runtime.read_api_pid
        original_process_exists = agentmemory_runtime.process_exists
        original_can_bind_api_port = agentmemory_runtime.can_bind_api_port
        original_listening_pid_for_api_port = agentmemory_runtime.listening_pid_for_api_port
        original_read_api_state = agentmemory_runtime.read_api_state
        try:
            agentmemory_runtime.read_api_pid = lambda: None  # type: ignore[assignment]
            agentmemory_runtime.process_exists = lambda pid: False  # type: ignore[assignment]
            agentmemory_runtime.can_bind_api_port = lambda host, port: True  # type: ignore[assignment]
            agentmemory_runtime.listening_pid_for_api_port = lambda host, port: None  # type: ignore[assignment]
            agentmemory_runtime.read_api_state = lambda: None  # type: ignore[assignment]

            payload = agentmemory_runtime.runtime_info()
        finally:
            agentmemory_runtime.read_api_pid = original_read_api_pid  # type: ignore[assignment]
            agentmemory_runtime.process_exists = original_process_exists  # type: ignore[assignment]
            agentmemory_runtime.can_bind_api_port = original_can_bind_api_port  # type: ignore[assignment]
            agentmemory_runtime.listening_pid_for_api_port = original_listening_pid_for_api_port  # type: ignore[assignment]
            agentmemory_runtime.read_api_state = original_read_api_state  # type: ignore[assignment]

        self.assertEqual(payload["api_runtime"]["status"], "available")
        self.assertTrue(payload["api_runtime"]["port_available"])
        self.assertEqual(payload["runtime_identity"]["profile"], "default")

    def test_api_runtime_diagnostics_reports_foreign_listener_conflict_when_other_pid_owns_port(self) -> None:
        generic = agentmemory_runtime.default_runtime_config()
        agentmemory_runtime.write_runtime_config(generic)

        original_read_api_pid = agentmemory_runtime.read_api_pid
        original_process_exists = agentmemory_runtime.process_exists
        original_can_bind_api_port = agentmemory_runtime.can_bind_api_port
        original_listening_pid_for_api_port = agentmemory_runtime.listening_pid_for_api_port
        original_read_api_state = agentmemory_runtime.read_api_state
        try:
            agentmemory_runtime.read_api_pid = lambda: 111  # type: ignore[assignment]
            agentmemory_runtime.process_exists = lambda pid: pid == 111  # type: ignore[assignment]
            agentmemory_runtime.can_bind_api_port = lambda host, port: False  # type: ignore[assignment]
            agentmemory_runtime.listening_pid_for_api_port = lambda host, port: 222  # type: ignore[assignment]
            agentmemory_runtime.read_api_state = lambda: {"pid": 111, "runtime_id": agentmemory_runtime.runtime_identity()["runtime_id"]}  # type: ignore[assignment]

            payload = agentmemory_runtime.runtime_info()
        finally:
            agentmemory_runtime.read_api_pid = original_read_api_pid  # type: ignore[assignment]
            agentmemory_runtime.process_exists = original_process_exists  # type: ignore[assignment]
            agentmemory_runtime.can_bind_api_port = original_can_bind_api_port  # type: ignore[assignment]
            agentmemory_runtime.listening_pid_for_api_port = original_listening_pid_for_api_port  # type: ignore[assignment]
            agentmemory_runtime.read_api_state = original_read_api_state  # type: ignore[assignment]

        self.assertEqual(payload["api_runtime"]["status"], "foreign_listener_conflict")
        self.assertEqual(payload["api_runtime"]["recorded_pid"], 111)
        self.assertEqual(payload["api_runtime"]["listener_pid"], 222)
        self.assertFalse(payload["api_runtime"]["recorded_pid_owns_listener"])

    def test_api_runtime_diagnostics_reports_running_untracked_for_matching_listener_without_pid_file(self) -> None:
        generic = agentmemory_runtime.default_runtime_config()
        generic["runtime"]["provider"] = "localjson"
        generic["providers"]["localjson"] = agentmemory_runtime.provider_class("localjson").default_provider_config(
            runtime_dir=self.temp_dir.name
        )
        agentmemory_runtime.write_runtime_config(generic)

        original_read_api_pid = agentmemory_runtime.read_api_pid
        original_process_exists = agentmemory_runtime.process_exists
        original_can_bind_api_port = agentmemory_runtime.can_bind_api_port
        original_listening_pid_for_api_port = agentmemory_runtime.listening_pid_for_api_port
        original_read_api_state = agentmemory_runtime.read_api_state
        original_api_health_payload = agentmemory_runtime.api_health_payload
        try:
            agentmemory_runtime.read_api_pid = lambda: None  # type: ignore[assignment]
            agentmemory_runtime.process_exists = lambda pid: False  # type: ignore[assignment]
            agentmemory_runtime.can_bind_api_port = lambda host, port: False  # type: ignore[assignment]
            agentmemory_runtime.listening_pid_for_api_port = lambda host, port: 222  # type: ignore[assignment]
            agentmemory_runtime.read_api_state = lambda: None  # type: ignore[assignment]
            agentmemory_runtime.api_health_payload = lambda host, port, timeout_seconds=1.0: {  # type: ignore[assignment]
                "ok": True,
                "runtime_identity": {"runtime_id": agentmemory_runtime.runtime_identity()["runtime_id"]},
            }

            payload = agentmemory_runtime.runtime_info()
        finally:
            agentmemory_runtime.read_api_pid = original_read_api_pid  # type: ignore[assignment]
            agentmemory_runtime.process_exists = original_process_exists  # type: ignore[assignment]
            agentmemory_runtime.can_bind_api_port = original_can_bind_api_port  # type: ignore[assignment]
            agentmemory_runtime.listening_pid_for_api_port = original_listening_pid_for_api_port  # type: ignore[assignment]
            agentmemory_runtime.read_api_state = original_read_api_state  # type: ignore[assignment]
            agentmemory_runtime.api_health_payload = original_api_health_payload  # type: ignore[assignment]

        self.assertEqual(payload["api_runtime"]["status"], "running_untracked")
        self.assertEqual(payload["api_runtime"]["listener_pid"], 222)
        self.assertTrue(payload["api_runtime"]["listener_runtime_matches_current"])


if __name__ == "__main__":
    unittest.main()
