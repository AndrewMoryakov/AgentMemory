import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agentmemory_interactive


class AgentMemoryInteractiveTests(unittest.TestCase):
    def make_context(self, **overrides):
        data = {
            'config_path': Path('agentmemory.config.json'),
            'env_path': Path('.env'),
            'venv_python': Path('.venv/Scripts/python.exe'),
            'api_host': '127.0.0.1',
            'api_port': 8765,
            'provider': 'mem0',
            'prompt_menu_enabled': True,
        }
        data.update(overrides)
        return agentmemory_interactive.InteractiveContext(**data)

    def test_onboarding_needed_when_files_missing(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        base = Path(temp_dir.name)
        self.assertTrue(agentmemory_interactive.onboarding_needed(config_path=base / 'agentmemory.config.json', venv_python=base / '.venv' / 'Scripts' / 'python.exe'))
        temp_dir.cleanup()

    def test_normalize_command_line_supports_aliases(self) -> None:
        self.assertEqual(agentmemory_interactive.normalize_command_line('/status'), ['status-clients', '--compact'])
        self.assertEqual(agentmemory_interactive.normalize_command_line('/provider localjson'), ['configure', '--provider', 'localjson'])
        self.assertEqual(agentmemory_interactive.normalize_command_line('/ui'), ['start-api'])

    def test_interactive_help_mentions_slash_commands(self) -> None:
        text = agentmemory_interactive.interactive_help(self.make_context())
        self.assertIn('/doctor', text)
        self.assertIn('/ui', text)

    def test_home_screen_contains_status_and_tips(self) -> None:
        text = agentmemory_interactive.render_home_screen(self.make_context())
        self.assertIn('AgentMemory Home', text)
        self.assertIn('Provider      mem0', text)
        self.assertIn('http://127.0.0.1:8765/ui', text)
        self.assertIn('Type / to open the command menu', text)

    def test_home_screen_mentions_basic_mode_when_menu_disabled(self) -> None:
        text = agentmemory_interactive.render_home_screen(self.make_context(prompt_menu_enabled=False))
        self.assertIn('basic prompt mode', text)

    def test_home_screen_renders_provider_notes_when_present(self) -> None:
        text = agentmemory_interactive.render_home_screen(
            self.make_context(provider_notes=("Provider requires scope for search.",))
        )
        self.assertIn('Provider notes', text)
        self.assertIn('Provider requires scope for search.', text)

    def test_prompt_toolkit_availability_requires_tty(self) -> None:
        with mock.patch('agentmemory_interactive.PromptSession', object()), \
             mock.patch('agentmemory_interactive.InMemoryHistory', object()), \
             mock.patch('agentmemory_interactive.CompleteStyle', object()), \
             mock.patch('agentmemory_interactive.sys.stdin.isatty', return_value=False), \
             mock.patch('agentmemory_interactive.sys.stdout.isatty', return_value=True):
            self.assertFalse(agentmemory_interactive.prompt_toolkit_available())


if __name__ == '__main__':
    unittest.main()
