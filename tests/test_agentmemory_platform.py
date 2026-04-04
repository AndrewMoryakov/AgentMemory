import unittest
from pathlib import Path

import agentmemory_platform


class AgentMemoryPlatformTests(unittest.TestCase):
    def test_launcher_path_uses_platform_suffix(self) -> None:
        base = Path("/tmp/agentmemory")
        path = agentmemory_platform.launcher_path(base, "run-agentmemory-mcp")
        self.assertIn(path.suffix, {".ps1", ".sh"})

    def test_launcher_command_includes_script_path(self) -> None:
        script = Path("/tmp/agentmemory/run-agentmemory-mcp.sh")
        command = agentmemory_platform.launcher_command(script)
        self.assertGreaterEqual(len(command), 2)
        self.assertEqual(command[-1], str(script))

    def test_venv_python_path_matches_platform_layout(self) -> None:
        base = Path("/tmp/agentmemory")
        path = agentmemory_platform.venv_python_path(base)
        self.assertTrue(str(path).endswith("python") or str(path).endswith("python.exe"))


if __name__ == "__main__":
    unittest.main()
