import unittest
import tempfile
import json
from pathlib import Path
from unittest import mock

import agentmemory.clients as agentmemory_clients


class AgentMemoryClientsTests(unittest.TestCase):
    def test_normalize_display_text_removes_ansi_and_unicode_checks(self) -> None:
        raw = "\u001b[32m\u2713\u001b[0m Connected\r\n"
        self.assertEqual(agentmemory_clients.normalize_display_text(raw), "[ok] Connected")

    def test_config_status_reports_missing_file_as_not_detected(self) -> None:
        missing = agentmemory_clients.Path(r"Z:\definitely-missing\mcp.json")
        payload = agentmemory_clients.config_status(missing, "mcpServers", "missing-client")
        self.assertFalse(payload["connected"])
        self.assertEqual(payload["details"], "not detected")

    def test_command_result_normalizes_stdout_and_stderr(self) -> None:
        completed = agentmemory_clients.subprocess.CompletedProcess(
            args=["pwsh"],
            returncode=0,
            stdout="\u001b[32m\u2713\u001b[0m ok",
            stderr="",
        )
        payload = agentmemory_clients.command_result("test", completed)
        self.assertEqual(payload["stdout"], "[ok] ok")

    def test_config_status_detects_stale_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp.json"
            path.write_text(json.dumps({
                "mcpServers": {
                    "agentmemory": {
                        "command": "pwsh",
                        "args": ["-File", "O:/user files/Projects/tools/AgentMemory/run-mem0-mcp.ps1"],
                    }
                }
            }), encoding="utf-8")
            payload = agentmemory_clients.config_status(path, "mcpServers", "test-client")
            self.assertTrue(payload["configured"])
            self.assertEqual(payload["health"], "stale_config")
            self.assertTrue(payload["stale_launcher"])

    def test_text_config_status_detects_configured_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"agentmemory":{"args":["-File","O:/user files/Projects/tools/AgentMemory/scripts/run-agentmemory-mcp.ps1"]}}', encoding="utf-8")
            payload = agentmemory_clients.text_config_status(path, "cli-client")
            self.assertTrue(payload["configured"])
            self.assertEqual(payload["health"], "configured")
            self.assertFalse(payload["stale_launcher"])

    def test_windows_client_paths_use_appdata_roaming(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appdata = Path(tmp) / "AppData" / "Roaming"
            with (
                mock.patch.object(agentmemory_clients.sys, "platform", "win32"),
                mock.patch.dict(agentmemory_clients.os.environ, {"APPDATA": str(appdata)}, clear=False),
            ):
                self.assertEqual(
                    agentmemory_clients.claude_desktop_config_path(),
                    appdata / "Claude" / "claude_desktop_config.json",
                )
                self.assertEqual(
                    agentmemory_clients.vscode_mcp_path(),
                    appdata / "Code" / "User" / "mcp.json",
                )
                self.assertEqual(
                    agentmemory_clients.roo_mcp_path(),
                    appdata / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "mcp_settings.json",
                )

    def test_macos_client_paths_use_application_support(self) -> None:
        home = Path("/Users/tester")
        with (
            mock.patch.object(agentmemory_clients.sys, "platform", "darwin"),
            mock.patch.object(agentmemory_clients.Path, "home", return_value=home),
        ):
            self.assertEqual(
                agentmemory_clients.claude_desktop_config_path(),
                home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
            )
            self.assertEqual(
                agentmemory_clients.vscode_mcp_path(),
                home / "Library" / "Application Support" / "Code" / "User" / "mcp.json",
            )
            self.assertEqual(
                agentmemory_clients.cline_cursor_mcp_path(),
                home / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "mcp_settings.json",
            )

    def test_linux_client_paths_use_xdg_config_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            with (
                mock.patch.object(agentmemory_clients.sys, "platform", "linux"),
                mock.patch.dict(agentmemory_clients.os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=False),
            ):
                self.assertEqual(
                    agentmemory_clients.claude_desktop_config_path(),
                    xdg / "Claude" / "claude_desktop_config.json",
                )
                self.assertEqual(
                    agentmemory_clients.vscode_mcp_path(),
                    xdg / "Code" / "User" / "mcp.json",
                )
                self.assertEqual(
                    agentmemory_clients.kilo_mcp_path(),
                    xdg / "Code" / "User" / "globalStorage" / "kilocode.kilo-code" / "settings" / "mcp_settings.json",
                )

    def test_linux_claude_desktop_path_prefers_existing_lowercase_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            fallback = xdg / "claude" / "claude_desktop_config.json"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            fallback.write_text("{}", encoding="utf-8")
            with (
                mock.patch.object(agentmemory_clients.sys, "platform", "linux"),
                mock.patch.dict(agentmemory_clients.os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=False),
            ):
                self.assertEqual(agentmemory_clients.claude_desktop_config_path(), fallback)

    def test_client_path_overrides_take_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "custom" / "claude.json"
            with mock.patch.dict(
                agentmemory_clients.os.environ,
                {
                    "AGENTMEMORY_CLAUDE_DESKTOP_CONFIG": str(custom),
                    "AGENTMEMORY_VSCODE_MCP_CONFIG": str(custom.with_name("vscode.json")),
                },
                clear=False,
            ):
                self.assertEqual(agentmemory_clients.claude_desktop_config_path(), custom)
                self.assertEqual(agentmemory_clients.vscode_mcp_path(), custom.with_name("vscode.json"))


if __name__ == "__main__":
    unittest.main()
