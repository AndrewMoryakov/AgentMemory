import unittest

import agentmemory_clients


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


if __name__ == "__main__":
    unittest.main()
