import json
import importlib.util
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

import agentmemory_runtime


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
        self.assertEqual(payload["config_source"], "generic")
        self.assertIn("capabilities", payload)
        self.assertIn("runtime_policy", payload)
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
        self.assertEqual(decoded["runtime"]["provider"], "mem0")

    def test_ensure_default_runtime_config_creates_generic_config(self) -> None:
        payload = agentmemory_runtime.ensure_default_runtime_config()

        self.assertEqual(payload["runtime"]["provider"], "mem0")
        self.assertTrue(agentmemory_runtime.CONFIG_PATH.exists())

    def test_provider_class_exposes_provider_specific_configuration_hooks(self) -> None:
        provider_type = agentmemory_runtime.provider_class("mem0")
        provider_config = provider_type.default_provider_config(runtime_dir="C:\\runtime")
        args = SimpleNamespace(
            openrouter_api_key="sk-test",
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

    def test_provider_registry_contains_second_test_provider(self) -> None:
        self.assertIn("localjson", agentmemory_runtime.provider_registry())
        self.assertIn("mem0", agentmemory_runtime.provider_registry())

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

    def test_memory_list_scopes_uses_active_provider(self) -> None:
        config = agentmemory_runtime.default_runtime_config()
        config["runtime"]["provider"] = "localjson"
        config["providers"]["localjson"] = agentmemory_runtime.provider_class("localjson").default_provider_config(
            runtime_dir=self.temp_dir.name
        )
        agentmemory_runtime.write_runtime_config(config)

        agentmemory_runtime.memory_add(messages=[{"role": "user", "content": "hello"}], user_id="default")
        payload = agentmemory_runtime.memory_list_scopes()

        self.assertEqual(payload["provider"], "localjson")
        self.assertEqual(payload["totals"]["users"], 1)


if __name__ == "__main__":
    unittest.main()
