import argparse
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

import agentmemory
import agentmemory_runtime


class AgentMemoryCoreTests(unittest.TestCase):
    def test_has_real_openrouter_key_rejects_placeholders(self) -> None:
        self.assertFalse(agentmemory.has_real_openrouter_key(None))
        self.assertFalse(agentmemory.has_real_openrouter_key("paste-your-openrouter-key-here"))
        self.assertFalse(agentmemory.has_real_openrouter_key("YOUR_OPENROUTER_API_KEY"))
        self.assertTrue(agentmemory.has_real_openrouter_key("sk-or-v1-real"))

    def test_doctor_exit_code_ignores_not_detected_clients(self) -> None:
        payload = {
            "local_server": {"ok": True},
            "results": [
                {"target": "codex", "detected": True, "health": "connected"},
                {"target": "cline", "detected": False, "health": "not_detected"},
            ],
        }
        self.assertEqual(agentmemory.doctor_exit_code(payload), 0)

    def test_doctor_exit_code_reports_client_issues(self) -> None:
        payload = {
            "local_server": {"ok": True},
            "results": [
                {"target": "codex", "detected": True, "health": "not_configured"},
            ],
        }
        self.assertEqual(agentmemory.doctor_exit_code(payload), 20)

    def test_doctor_exit_code_reports_local_server_failure(self) -> None:
        payload = {
            "local_server": {"ok": False},
            "results": [
                {"target": "codex", "detected": True, "health": "connected"},
            ],
        }
        self.assertEqual(agentmemory.doctor_exit_code(payload), 10)

    def test_run_clients_helper_handles_non_json_output(self) -> None:
        original_run = agentmemory.run
        try:
            class FakeResult:
                returncode = 0
                stdout = "not-json"

            agentmemory.run = lambda *args, **kwargs: FakeResult()  # type: ignore[assignment]
            code, payload, raw = agentmemory.run_clients_helper("status")
            self.assertEqual(code, 0)
            self.assertIsNone(payload)
            self.assertEqual(raw, "not-json")
        finally:
            agentmemory.run = original_run

    def test_print_status_payload_json_is_stable(self) -> None:
        payload = {"server_name": "agentmemory", "results": [{"target": "codex", "connected": True}]}
        encoded = json.dumps(payload, ensure_ascii=True, indent=2)
        self.assertIn('"server_name": "agentmemory"', encoded)

    def test_command_configure_applies_provider_switch_and_runtime_fields(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        base = Path(temp_dir.name)
        original_config_path = agentmemory_runtime.CONFIG_PATH
        original_env_path = agentmemory_runtime.ENV_PATH
        original_agentmemory_config_path = agentmemory.CONFIG_PATH
        original_agentmemory_env_path = agentmemory.ENV_PATH
        try:
            agentmemory_runtime.CONFIG_PATH = base / "agentmemory.config.json"
            agentmemory_runtime.ENV_PATH = base / ".env"
            agentmemory.CONFIG_PATH = agentmemory_runtime.CONFIG_PATH
            agentmemory.ENV_PATH = agentmemory_runtime.ENV_PATH
            agentmemory_runtime.write_runtime_config(agentmemory_runtime.default_runtime_config())

            parser = agentmemory.build_parser()
            args = parser.parse_args(["configure", "--provider", "localjson", "--api-port", "9777"])
            result = agentmemory.command_configure(args)
            config = agentmemory_runtime.load_runtime_config()

            self.assertEqual(result, 0)
            self.assertEqual(config["runtime"]["provider"], "localjson")
            self.assertEqual(config["runtime"]["api_port"], 9777)
        finally:
            agentmemory_runtime.CONFIG_PATH = original_config_path
            agentmemory_runtime.ENV_PATH = original_env_path
            agentmemory.CONFIG_PATH = original_agentmemory_config_path
            agentmemory.ENV_PATH = original_agentmemory_env_path
            agentmemory_runtime.clear_caches()
            temp_dir.cleanup()

    def test_provider_certify_subcommand_lists_targets_as_json(self) -> None:
        parser = agentmemory.build_parser()
        args = parser.parse_args(["provider-certify", "--list", "--json"])
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()
        try:
            agentmemory.sys.stdout = buffer
            result = agentmemory.command_provider_certify(args)
        finally:
            agentmemory.sys.stdout = original_stdout

        payload = json.loads(buffer.getvalue())
        self.assertEqual(result, 0)
        self.assertIn("targets", payload)
        self.assertTrue(any(item["provider_name"] == "localjson" for item in payload["targets"]))

    def test_provider_certify_subcommand_reports_provider(self) -> None:
        parser = agentmemory.build_parser()
        args = parser.parse_args(["provider-certify", "mem0", "--json"])
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()
        try:
            agentmemory.sys.stdout = buffer
            result = agentmemory.command_provider_certify(args)
        finally:
            agentmemory.sys.stdout = original_stdout

        payload = json.loads(buffer.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload["provider_name"], "mem0")
        self.assertEqual(payload["verdict"], "certified")
        self.assertEqual(payload["status_code"], "certified")

    def test_provider_certify_subcommand_summary_only_omits_test_log(self) -> None:
        parser = agentmemory.build_parser()
        args = parser.parse_args(["provider-certify", "mem0", "--json", "--run-tests", "--summary-only"])
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()
        try:
            agentmemory.sys.stdout = buffer
            with mock.patch.object(
                agentmemory,
                "certification_report_json",
                return_value=0,
            ) as mocked_report:
                result = agentmemory.command_provider_certify(args)
        finally:
            agentmemory.sys.stdout = original_stdout

        self.assertEqual(result, 0)
        mocked_report.assert_called_once_with("mem0", run_tests=True, summary_only=True)

    def test_provider_certify_requires_provider_without_list(self) -> None:
        parser = agentmemory.build_parser()
        args = parser.parse_args(["provider-certify"])
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()
        try:
            agentmemory.sys.stdout = buffer
            result = agentmemory.command_provider_certify(args)
        finally:
            agentmemory.sys.stdout = original_stdout

        self.assertEqual(result, 2)
        self.assertIn("provider is required unless --list is used", buffer.getvalue())

    def test_doctor_prints_provider_capability_summary(self) -> None:
        original_runtime_info = agentmemory.runtime_info
        original_get_provider = agentmemory.get_provider
        original_load_runtime_config_with_source = agentmemory.load_runtime_config_with_source
        original_env_path = agentmemory.ENV_PATH
        original_venv_python = agentmemory.VENV_PYTHON
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()

        class FakeProvider:
            def prerequisite_checks(self):
                return []

            def doctor_rows(self):
                return []

            def dependency_checks(self):
                return []

        try:
            agentmemory.runtime_info = lambda: {  # type: ignore[assignment]
                "provider": "mem0",
                "config_path": "fake-config.json",
                "api_host": "127.0.0.1",
                "api_port": 8765,
                "runtime_policy": {"transport_mode": "owner_process_proxy"},
                "capabilities": {
                    "supports_semantic_search": True,
                    "supports_text_search": False,
                    "supports_filters": True,
                    "supports_metadata_filters": True,
                    "supports_rerank": True,
                    "supports_update": True,
                    "supports_delete": True,
                "supports_scopeless_list": False,
                "requires_scope_for_list": True,
                "requires_scope_for_search": True,
                "supports_owner_process_mode": True,
                "supports_scope_inventory": True,
            },
            }
            agentmemory.get_provider = lambda: FakeProvider()  # type: ignore[assignment]
            agentmemory.load_runtime_config_with_source = lambda: ({}, "generic", Path("fake-config.json"))  # type: ignore[assignment]
            agentmemory.ENV_PATH = Path("fake.env")
            agentmemory.VENV_PYTHON = Path("missing-python.exe")
            agentmemory.sys.stdout = buffer
            result = agentmemory.command_doctor(argparse.Namespace())
        finally:
            agentmemory.runtime_info = original_runtime_info  # type: ignore[assignment]
            agentmemory.get_provider = original_get_provider  # type: ignore[assignment]
            agentmemory.load_runtime_config_with_source = original_load_runtime_config_with_source  # type: ignore[assignment]
            agentmemory.ENV_PATH = original_env_path
            agentmemory.VENV_PYTHON = original_venv_python
            agentmemory.sys.stdout = original_stdout

        output = buffer.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("Search mode: semantic", output)
        self.assertIn("Supports filters: yes", output)
        self.assertIn("Search requires scope: yes", output)
        self.assertIn("Owner-process mode: yes", output)
        self.assertIn("Transport mode: owner_process_proxy", output)
        self.assertIn("Operational guidance:", output)
        self.assertIn("requires scope", output)

    def test_doctor_clients_json_includes_provider_guidance(self) -> None:
        original_run_clients_helper = agentmemory.run_clients_helper
        original_runtime_info = agentmemory.runtime_info
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()
        try:
            agentmemory.run_clients_helper = lambda *_args: (0, {  # type: ignore[assignment]
                "local_server": {"ok": True},
                "results": [{"target": "codex", "detected": True, "connected": True, "health": "connected"}],
            }, "")
            agentmemory.runtime_info = lambda: {  # type: ignore[assignment]
                "provider": "mem0",
                "runtime_policy": {"transport_mode": "owner_process_proxy"},
                "capabilities": {
                    "supports_semantic_search": True,
                    "supports_text_search": False,
                    "supports_filters": True,
                    "supports_metadata_filters": True,
                    "supports_rerank": True,
                    "supports_update": True,
                    "supports_delete": True,
                "supports_scopeless_list": False,
                "requires_scope_for_list": True,
                "requires_scope_for_search": True,
                "supports_owner_process_mode": True,
                "supports_scope_inventory": True,
            },
            }
            agentmemory.sys.stdout = buffer
            rc = agentmemory.command_doctor_clients(argparse.Namespace(json=True, compact=False, table=False))
        finally:
            agentmemory.run_clients_helper = original_run_clients_helper  # type: ignore[assignment]
            agentmemory.runtime_info = original_runtime_info  # type: ignore[assignment]
            agentmemory.sys.stdout = original_stdout

        payload = json.loads(buffer.getvalue().split('\n', 3)[-1])
        self.assertEqual(rc, 0)
        self.assertEqual(payload["provider"], "mem0")
        self.assertEqual(payload["runtime_policy"]["transport_mode"], "owner_process_proxy")
        self.assertTrue(payload["provider_guidance"])
        self.assertTrue(payload["client_runtime_guidance"])

    def test_status_clients_json_includes_client_runtime_guidance(self) -> None:
        original_run_clients_helper = agentmemory.run_clients_helper
        original_runtime_info = agentmemory.runtime_info
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()
        try:
            agentmemory.run_clients_helper = lambda *_args: (0, {  # type: ignore[assignment]
                "results": [{"target": "cursor", "configured": True, "health": "stale_config", "stale_launcher": True}],
            }, "")
            agentmemory.runtime_info = lambda: {  # type: ignore[assignment]
                "provider": "mem0",
                "runtime_policy": {"transport_mode": "owner_process_proxy"},
                "capabilities": {
                    "supports_semantic_search": True,
                    "supports_text_search": False,
                    "supports_filters": True,
                    "supports_metadata_filters": True,
                    "supports_rerank": True,
                    "supports_update": True,
                    "supports_delete": True,
                "supports_scopeless_list": False,
                "requires_scope_for_list": True,
                "requires_scope_for_search": True,
                "supports_owner_process_mode": True,
                "supports_scope_inventory": True,
            },
            }
            agentmemory.sys.stdout = buffer
            rc = agentmemory.command_status_clients(argparse.Namespace(json=True, compact=False, table=False))
        finally:
            agentmemory.run_clients_helper = original_run_clients_helper  # type: ignore[assignment]
            agentmemory.runtime_info = original_runtime_info  # type: ignore[assignment]
            agentmemory.sys.stdout = original_stdout

        payload = json.loads(buffer.getvalue().split('\n', 3)[-1])
        self.assertEqual(rc, 0)
        self.assertEqual(payload["runtime_policy"]["transport_mode"], "owner_process_proxy")
        self.assertTrue(payload["client_runtime_guidance"])

    def test_connect_clients_prints_client_runtime_guidance(self) -> None:
        original_run_clients_helper = agentmemory.run_clients_helper
        original_runtime_info = agentmemory.runtime_info
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()
        try:
            agentmemory.run_clients_helper = lambda *_args: (0, {  # type: ignore[assignment]
                "results": [{"target": "cursor", "status": "updated"}],
            }, "")
            agentmemory.runtime_info = lambda: {  # type: ignore[assignment]
                "provider": "localjson",
                "runtime_policy": {"transport_mode": "direct"},
                "capabilities": {
                    "supports_semantic_search": False,
                    "supports_text_search": True,
                    "supports_filters": True,
                    "supports_metadata_filters": True,
                    "supports_rerank": False,
                    "supports_update": True,
                    "supports_delete": True,
                "supports_scopeless_list": True,
                "requires_scope_for_list": False,
                "requires_scope_for_search": False,
                "supports_owner_process_mode": False,
                "supports_scope_inventory": True,
            },
            }
            agentmemory.sys.stdout = buffer
            rc = agentmemory.command_connect_clients(argparse.Namespace())
        finally:
            agentmemory.run_clients_helper = original_run_clients_helper  # type: ignore[assignment]
            agentmemory.runtime_info = original_runtime_info  # type: ignore[assignment]
            agentmemory.sys.stdout = original_stdout

        output = buffer.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Operational guidance:", output)
        self.assertIn("does not support rerank", output)


if __name__ == "__main__":
    unittest.main()
