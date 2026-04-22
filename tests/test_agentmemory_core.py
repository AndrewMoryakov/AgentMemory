import argparse
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

import agentmemory.cli as agentmemory
import agentmemory.runtime.config as agentmemory_runtime


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

    def test_command_rebuild_scope_registry_prints_summary(self) -> None:
        original_rebuild_scope_registry = agentmemory.rebuild_scope_registry
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()
        try:
            agentmemory.rebuild_scope_registry = lambda: {  # type: ignore[assignment]
                "provider": "mem0",
                "records": 3,
                "users": 1,
                "agents": 1,
                "runs": 1,
            }
            agentmemory.sys.stdout = buffer

            rc = agentmemory.command_rebuild_scope_registry(argparse.Namespace())
        finally:
            agentmemory.rebuild_scope_registry = original_rebuild_scope_registry  # type: ignore[assignment]
            agentmemory.sys.stdout = original_stdout

        self.assertEqual(rc, 0)
        self.assertIn("Rebuilt scope registry for provider 'mem0'", buffer.getvalue())

    def test_command_export_memories_invokes_ops_cli_export(self) -> None:
        original_run = agentmemory.run
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()
        captured: dict[str, object] = {}

        class FakeCompleted:
            def __init__(self) -> None:
                self.returncode = 0
                self.stdout = '{"exported": 2}'
                self.stderr = ""

        try:
            def fake_run(command, **kwargs):
                captured["command"] = list(command)
                return FakeCompleted()

            agentmemory.run = fake_run  # type: ignore[assignment]
            agentmemory.sys.stdout = buffer
            rc = agentmemory.command_export_memories(argparse.Namespace(path="memories.jsonl"))
        finally:
            agentmemory.run = original_run  # type: ignore[assignment]
            agentmemory.sys.stdout = original_stdout

        self.assertEqual(rc, 0)
        self.assertIn("export", captured["command"])
        self.assertIn("memories.jsonl", captured["command"])
        self.assertIn('"exported": 2', buffer.getvalue())

    def test_command_import_memories_invokes_ops_cli_import(self) -> None:
        original_run = agentmemory.run
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()
        captured: dict[str, object] = {}

        class FakeCompleted:
            def __init__(self) -> None:
                self.returncode = 0
                self.stdout = '{"imported": 2}'
                self.stderr = ""

        try:
            def fake_run(command, **kwargs):
                captured["command"] = list(command)
                return FakeCompleted()

            agentmemory.run = fake_run  # type: ignore[assignment]
            agentmemory.sys.stdout = buffer
            rc = agentmemory.command_import_memories(argparse.Namespace(path="memories.jsonl"))
        finally:
            agentmemory.run = original_run  # type: ignore[assignment]
            agentmemory.sys.stdout = original_stdout

        self.assertEqual(rc, 0)
        self.assertIn("import", captured["command"])
        self.assertIn("memories.jsonl", captured["command"])
        self.assertIn('"imported": 2', buffer.getvalue())

    def test_resolve_api_start_port_returns_requested_port_when_free(self) -> None:
        original_can_bind_api_port = agentmemory.can_bind_api_port
        try:
            agentmemory.can_bind_api_port = lambda host, port: True  # type: ignore[assignment]
            selected_port, message = agentmemory.resolve_api_start_port("127.0.0.1", 8765)
        finally:
            agentmemory.can_bind_api_port = original_can_bind_api_port  # type: ignore[assignment]

        self.assertEqual(selected_port, 8765)
        self.assertIsNone(message)

    def test_command_start_api_uses_free_port_and_updates_config_when_requested_port_is_busy(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        base = Path(temp_dir.name)
        original_config_path = agentmemory_runtime.CONFIG_PATH
        original_env_path = agentmemory_runtime.ENV_PATH
        original_agentmemory_config_path = agentmemory.CONFIG_PATH
        original_agentmemory_env_path = agentmemory.ENV_PATH
        original_resolve_api_start_port = agentmemory.resolve_api_start_port
        original_start_api_process = agentmemory.start_api_process
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()
        started: dict[str, object] = {}
        try:
            agentmemory_runtime.CONFIG_PATH = base / "agentmemory.config.json"
            agentmemory_runtime.ENV_PATH = base / ".env"
            agentmemory.CONFIG_PATH = agentmemory_runtime.CONFIG_PATH
            agentmemory.ENV_PATH = agentmemory_runtime.ENV_PATH
            agentmemory_runtime.write_runtime_config(agentmemory_runtime.default_runtime_config())

            agentmemory.resolve_api_start_port = lambda host, port: (8766, "Port 8765 is busy; using 8766 instead and updating runtime config.")  # type: ignore[assignment]

            def fake_start_api_process(host: str, port: int):
                started["host"] = host
                started["port"] = port
                return True, f"AgentMemory API started on http://{host}:{port}"

            agentmemory.start_api_process = fake_start_api_process  # type: ignore[assignment]
            agentmemory.sys.stdout = buffer

            rc = agentmemory.command_start_api(argparse.Namespace(host="127.0.0.1", port=8765))
            updated = agentmemory_runtime.load_runtime_config()
        finally:
            agentmemory_runtime.CONFIG_PATH = original_config_path
            agentmemory_runtime.ENV_PATH = original_env_path
            agentmemory.CONFIG_PATH = original_agentmemory_config_path
            agentmemory.ENV_PATH = original_agentmemory_env_path
            agentmemory.resolve_api_start_port = original_resolve_api_start_port  # type: ignore[assignment]
            agentmemory.start_api_process = original_start_api_process  # type: ignore[assignment]
            agentmemory.sys.stdout = original_stdout
            agentmemory_runtime.clear_caches()
            temp_dir.cleanup()

        self.assertEqual(rc, 0)
        self.assertEqual(started["host"], "127.0.0.1")
        self.assertEqual(started["port"], 8766)
        self.assertEqual(updated["runtime"]["api_port"], 8766)
        self.assertIn("Port 8765 is busy; using 8766 instead", buffer.getvalue())

    def test_start_api_process_adopts_matching_runtime_listener_without_pid_file(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        base = Path(temp_dir.name)
        original_api_pid_file = agentmemory.API_PID_FILE
        original_managed_api_listener_pid = agentmemory.managed_api_listener_pid
        original_read_api_pid = agentmemory.read_api_pid
        original_process_exists = agentmemory.process_exists
        original_api_is_ready = agentmemory.api_is_ready
        original_write_api_state = agentmemory.write_api_state
        captured: dict[str, object] = {}
        try:
            agentmemory.API_PID_FILE = base / "agentmemory-api.pid"
            agentmemory.read_api_pid = lambda: None  # type: ignore[assignment]
            agentmemory.process_exists = lambda pid: False  # type: ignore[assignment]
            agentmemory.api_is_ready = lambda host, port, timeout_seconds=1.0: False  # type: ignore[assignment]
            agentmemory.managed_api_listener_pid = lambda host, port: 222  # type: ignore[assignment]
            agentmemory.write_api_state = lambda **kwargs: captured.update(kwargs)  # type: ignore[assignment]

            ok_result, message = agentmemory.start_api_process("127.0.0.1", 8765)
            written_pid = (base / "agentmemory-api.pid").read_text(encoding="ascii")
        finally:
            agentmemory.API_PID_FILE = original_api_pid_file
            agentmemory.managed_api_listener_pid = original_managed_api_listener_pid  # type: ignore[assignment]
            agentmemory.read_api_pid = original_read_api_pid  # type: ignore[assignment]
            agentmemory.process_exists = original_process_exists  # type: ignore[assignment]
            agentmemory.api_is_ready = original_api_is_ready  # type: ignore[assignment]
            agentmemory.write_api_state = original_write_api_state  # type: ignore[assignment]
            temp_dir.cleanup()

        self.assertTrue(ok_result)
        self.assertIn("adopted existing runtime listener", message)
        self.assertEqual(written_pid, "222")
        self.assertEqual(captured["pid"], 222)

    def test_stop_api_process_stops_matching_runtime_listener_without_pid_file(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        base = Path(temp_dir.name)
        original_api_pid_file = agentmemory.API_PID_FILE
        original_remove_api_state = agentmemory.remove_api_state
        original_managed_api_listener_pid = agentmemory.managed_api_listener_pid
        original_read_api_pid = agentmemory.read_api_pid
        original_process_exists = agentmemory.process_exists
        original_is_windows = agentmemory.is_windows
        original_os_kill = agentmemory.os.kill
        original_time_sleep = agentmemory.time.sleep
        killed: dict[str, object] = {}
        process_states = iter([True, False])
        try:
            agentmemory.API_PID_FILE = base / "agentmemory-api.pid"
            agentmemory.read_api_pid = lambda: None  # type: ignore[assignment]
            agentmemory.managed_api_listener_pid = lambda host, port: 333  # type: ignore[assignment]
            agentmemory.process_exists = lambda pid: next(process_states)  # type: ignore[assignment]
            agentmemory.is_windows = lambda: False  # type: ignore[assignment]
            agentmemory.os.kill = lambda pid, sig: killed.update({"pid": pid, "sig": sig})  # type: ignore[assignment]
            agentmemory.time.sleep = lambda seconds: None  # type: ignore[assignment]
            agentmemory.remove_api_state = lambda: None  # type: ignore[assignment]

            ok_result, message = agentmemory.stop_api_process()
        finally:
            agentmemory.API_PID_FILE = original_api_pid_file
            agentmemory.remove_api_state = original_remove_api_state  # type: ignore[assignment]
            agentmemory.managed_api_listener_pid = original_managed_api_listener_pid  # type: ignore[assignment]
            agentmemory.read_api_pid = original_read_api_pid  # type: ignore[assignment]
            agentmemory.process_exists = original_process_exists  # type: ignore[assignment]
            agentmemory.is_windows = original_is_windows  # type: ignore[assignment]
            agentmemory.os.kill = original_os_kill  # type: ignore[assignment]
            agentmemory.time.sleep = original_time_sleep  # type: ignore[assignment]
            temp_dir.cleanup()

        self.assertTrue(ok_result)
        self.assertEqual(killed["pid"], 333)
        self.assertIn("Stopped AgentMemory API process 333", message)

    def test_stop_api_process_windows_tries_graceful_before_force(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        base = Path(temp_dir.name)
        original_api_pid_file = agentmemory.API_PID_FILE
        original_remove_api_state = agentmemory.remove_api_state
        original_managed_api_listener_pid = agentmemory.managed_api_listener_pid
        original_read_api_pid = agentmemory.read_api_pid
        original_process_exists = agentmemory.process_exists
        original_is_windows = agentmemory.is_windows
        original_subprocess_run = agentmemory.subprocess.run
        original_time_sleep = agentmemory.time.sleep
        commands: list[list[str]] = []
        process_states = iter([True, True, False])

        class FakeCompleted:
            def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        try:
            agentmemory.API_PID_FILE = base / "agentmemory-api.pid"
            agentmemory.read_api_pid = lambda: None  # type: ignore[assignment]
            agentmemory.managed_api_listener_pid = lambda host, port: 333  # type: ignore[assignment]
            agentmemory.process_exists = lambda pid: next(process_states)  # type: ignore[assignment]
            agentmemory.is_windows = lambda: True  # type: ignore[assignment]
            agentmemory.time.sleep = lambda seconds: None  # type: ignore[assignment]
            agentmemory.remove_api_state = lambda: None  # type: ignore[assignment]

            def fake_run(command, **kwargs):
                commands.append(list(command))
                return FakeCompleted(stdout="terminated")

            agentmemory.subprocess.run = fake_run  # type: ignore[assignment]

            ok_result, message = agentmemory.stop_api_process()
        finally:
            agentmemory.API_PID_FILE = original_api_pid_file
            agentmemory.remove_api_state = original_remove_api_state  # type: ignore[assignment]
            agentmemory.managed_api_listener_pid = original_managed_api_listener_pid  # type: ignore[assignment]
            agentmemory.read_api_pid = original_read_api_pid  # type: ignore[assignment]
            agentmemory.process_exists = original_process_exists  # type: ignore[assignment]
            agentmemory.is_windows = original_is_windows  # type: ignore[assignment]
            agentmemory.subprocess.run = original_subprocess_run  # type: ignore[assignment]
            agentmemory.time.sleep = original_time_sleep  # type: ignore[assignment]
            temp_dir.cleanup()

        self.assertTrue(ok_result)
        self.assertEqual(commands, [["taskkill", "/PID", "333"]])
        self.assertIn("Stopped AgentMemory API process 333", message)

    def test_stop_api_process_windows_escalates_to_force_when_graceful_fails(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        base = Path(temp_dir.name)
        original_api_pid_file = agentmemory.API_PID_FILE
        original_remove_api_state = agentmemory.remove_api_state
        original_managed_api_listener_pid = agentmemory.managed_api_listener_pid
        original_read_api_pid = agentmemory.read_api_pid
        original_process_exists = agentmemory.process_exists
        original_is_windows = agentmemory.is_windows
        original_subprocess_run = agentmemory.subprocess.run
        original_time_sleep = agentmemory.time.sleep
        original_time_time = agentmemory.time.time
        original_stop_grace = agentmemory.API_STOP_GRACE_SECONDS
        commands: list[list[str]] = []
        process_states = iter([True, True, True, True, False])
        fake_clock = iter([0.0, 0.0, 0.02, 0.02, 0.03, 0.03])

        class FakeCompleted:
            def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        try:
            agentmemory.API_PID_FILE = base / "agentmemory-api.pid"
            agentmemory.read_api_pid = lambda: None  # type: ignore[assignment]
            agentmemory.managed_api_listener_pid = lambda host, port: 333  # type: ignore[assignment]
            agentmemory.process_exists = lambda pid: next(process_states)  # type: ignore[assignment]
            agentmemory.is_windows = lambda: True  # type: ignore[assignment]
            agentmemory.time.sleep = lambda seconds: None  # type: ignore[assignment]
            agentmemory.time.time = lambda: next(fake_clock)  # type: ignore[assignment]
            agentmemory.remove_api_state = lambda: None  # type: ignore[assignment]
            agentmemory.API_STOP_GRACE_SECONDS = 0.01  # type: ignore[assignment]

            def fake_run(command, **kwargs):
                commands.append(list(command))
                return FakeCompleted(stdout="terminated")

            agentmemory.subprocess.run = fake_run  # type: ignore[assignment]

            ok_result, message = agentmemory.stop_api_process()
        finally:
            agentmemory.API_PID_FILE = original_api_pid_file
            agentmemory.remove_api_state = original_remove_api_state  # type: ignore[assignment]
            agentmemory.managed_api_listener_pid = original_managed_api_listener_pid  # type: ignore[assignment]
            agentmemory.read_api_pid = original_read_api_pid  # type: ignore[assignment]
            agentmemory.process_exists = original_process_exists  # type: ignore[assignment]
            agentmemory.is_windows = original_is_windows  # type: ignore[assignment]
            agentmemory.subprocess.run = original_subprocess_run  # type: ignore[assignment]
            agentmemory.time.sleep = original_time_sleep  # type: ignore[assignment]
            agentmemory.time.time = original_time_time  # type: ignore[assignment]
            agentmemory.API_STOP_GRACE_SECONDS = original_stop_grace  # type: ignore[assignment]
            temp_dir.cleanup()

        self.assertTrue(ok_result)
        self.assertEqual(commands, [["taskkill", "/PID", "333"], ["taskkill", "/PID", "333", "/F"]])
        self.assertIn("Stopped AgentMemory API process 333", message)

    def test_start_api_process_waits_for_listener_pid_and_records_real_listener(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        base = Path(temp_dir.name)
        original_api_pid_file = agentmemory.API_PID_FILE
        original_api_log_file = agentmemory.API_LOG_FILE
        original_api_err_file = agentmemory.API_ERR_FILE
        original_subprocess_popen = agentmemory.subprocess.Popen
        original_listening_pid_for_api_port = agentmemory.listening_pid_for_api_port
        original_api_is_ready = agentmemory.api_is_ready
        original_read_api_pid = agentmemory.read_api_pid
        original_process_exists = agentmemory.process_exists
        original_managed_api_listener_pid = agentmemory.managed_api_listener_pid
        original_write_api_state = agentmemory.write_api_state
        original_time_sleep = agentmemory.time.sleep
        captured: dict[str, object] = {}

        class FakeProcess:
            pid = 111

            def poll(self):
                return 0

        ready_checks = {"count": 0}

        try:
            agentmemory.API_PID_FILE = base / "agentmemory-api.pid"
            agentmemory.API_LOG_FILE = base / "agentmemory-api.log"
            agentmemory.API_ERR_FILE = base / "agentmemory-api.err.log"
            agentmemory.read_api_pid = lambda: None  # type: ignore[assignment]
            agentmemory.process_exists = lambda pid: False  # type: ignore[assignment]
            agentmemory.managed_api_listener_pid = lambda host, port: None  # type: ignore[assignment]
            agentmemory.subprocess.Popen = lambda *args, **kwargs: FakeProcess()  # type: ignore[assignment]
            agentmemory.listening_pid_for_api_port = lambda host, port: 222  # type: ignore[assignment]

            def fake_api_is_ready(host: str, port: int, timeout_seconds: float = 1.0) -> bool:
                ready_checks["count"] += 1
                return ready_checks["count"] >= 3

            agentmemory.api_is_ready = fake_api_is_ready  # type: ignore[assignment]
            agentmemory.write_api_state = lambda **kwargs: captured.update(kwargs)  # type: ignore[assignment]
            agentmemory.time.sleep = lambda seconds: None  # type: ignore[assignment]

            ok_result, message = agentmemory.start_api_process("127.0.0.1", 8765)
            written_pid = (base / "agentmemory-api.pid").read_text(encoding="ascii")
        finally:
            agentmemory.API_PID_FILE = original_api_pid_file
            agentmemory.API_LOG_FILE = original_api_log_file
            agentmemory.API_ERR_FILE = original_api_err_file
            agentmemory.subprocess.Popen = original_subprocess_popen  # type: ignore[assignment]
            agentmemory.listening_pid_for_api_port = original_listening_pid_for_api_port  # type: ignore[assignment]
            agentmemory.api_is_ready = original_api_is_ready  # type: ignore[assignment]
            agentmemory.read_api_pid = original_read_api_pid  # type: ignore[assignment]
            agentmemory.process_exists = original_process_exists  # type: ignore[assignment]
            agentmemory.managed_api_listener_pid = original_managed_api_listener_pid  # type: ignore[assignment]
            agentmemory.write_api_state = original_write_api_state  # type: ignore[assignment]
            agentmemory.time.sleep = original_time_sleep  # type: ignore[assignment]
            temp_dir.cleanup()

        self.assertTrue(ok_result)
        self.assertIn("PID 222", message)
        self.assertEqual(written_pid, "222")
        self.assertEqual(captured["pid"], 222)

    def test_profile_commands_create_list_and_use_profiles(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        base = Path(temp_dir.name)
        original_config_path = agentmemory_runtime.CONFIG_PATH
        original_env_path = agentmemory_runtime.ENV_PATH
        original_agentmemory_config_path = agentmemory.CONFIG_PATH
        original_agentmemory_env_path = agentmemory.ENV_PATH
        original_stdout = agentmemory.sys.stdout
        buffer = StringIO()
        try:
            agentmemory_runtime.CONFIG_PATH = base / "agentmemory.config.json"
            agentmemory_runtime.ENV_PATH = base / ".env"
            agentmemory.CONFIG_PATH = agentmemory_runtime.CONFIG_PATH
            agentmemory.ENV_PATH = agentmemory_runtime.ENV_PATH
            agentmemory_runtime.write_runtime_config(agentmemory_runtime.default_runtime_config())

            parser = agentmemory.build_parser()
            rc_create = agentmemory.command_profile_create(parser.parse_args(["profile-create", "staging"]))
            agentmemory.sys.stdout = buffer
            rc_use = agentmemory.command_profile_use(parser.parse_args(["profile-use", "staging"]))
            rc_list = agentmemory.command_profile_list(parser.parse_args(["profile-list"]))
        finally:
            agentmemory_runtime.CONFIG_PATH = original_config_path
            agentmemory_runtime.ENV_PATH = original_env_path
            agentmemory.CONFIG_PATH = original_agentmemory_config_path
            agentmemory.ENV_PATH = original_agentmemory_env_path
            agentmemory.sys.stdout = original_stdout
            agentmemory_runtime.clear_caches()
            temp_dir.cleanup()

        output = buffer.getvalue()
        self.assertEqual(rc_create, 0)
        self.assertEqual(rc_use, 0)
        self.assertEqual(rc_list, 0)
        self.assertIn("* staging", output)

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
                "scope_registry": {"status": "ok"},
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
        self.assertIn("Env file: not present at fake.env", output)

    def test_doctor_warns_when_scope_registry_needs_rebuild_without_changing_exit_behavior(self) -> None:
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
                "scope_registry": {
                    "status": "needs_rebuild",
                    "last_failed_operation": "add",
                    "memory_id": "abc",
                    "last_error": "OperationalError: boom",
                },
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
        self.assertIn("Scope registry needs rebuild after add for memory abc.", output)
        self.assertIn("Scope registry last error: OperationalError: boom", output)

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
