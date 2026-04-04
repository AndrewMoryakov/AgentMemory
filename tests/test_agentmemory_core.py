import json
import unittest

import agentmemory


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


if __name__ == "__main__":
    unittest.main()

