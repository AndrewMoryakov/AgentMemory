import unittest
import tempfile
import json
from pathlib import Path

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
            path.write_text('{"agentmemory":{"args":["-File","O:/user files/Projects/tools/AgentMemory/run-agentmemory-mcp.ps1"]}}', encoding="utf-8")
            payload = agentmemory_clients.text_config_status(path, "cli-client")
            self.assertTrue(payload["configured"])
            self.assertEqual(payload["health"], "configured")
            self.assertFalse(payload["stale_launcher"])


if __name__ == "__main__":
    unittest.main()
