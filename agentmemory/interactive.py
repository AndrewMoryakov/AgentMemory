from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.shortcuts import CompleteStyle
except Exception:  # pragma: no cover
    PromptSession = None
    Completion = None
    Completer = object  # type: ignore[assignment]
    InMemoryHistory = None
    CompleteStyle = None


@dataclass
class InteractiveContext:
    config_path: Path
    env_path: Path
    venv_python: Path
    api_host: str
    api_port: int
    provider: str = 'mem0'
    provider_notes: tuple[str, ...] = ()
    prompt_menu_enabled: bool = False


SLASH_COMMANDS: dict[str, str] = {
    '/help': 'Show shell help',
    '/install': 'Run the installer workflow',
    '/configure': 'Configure provider or runtime settings',
    '/provider': 'Quick provider switch',
    '/doctor': 'Run diagnostics',
    '/start': 'Start the local API',
    '/stop': 'Stop the local API',
    '/ui': 'Start API and print console URL',
    '/mcp': 'Run MCP smoke test',
    '/status': 'Show client connection status',
    '/clients': 'Run client diagnostics',
    '/snippets': 'Print MCP snippets',
    '/exit': 'Exit the shell',
}


class SlashCommandCompleter(Completer):  # type: ignore[misc]
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith('/'):
            return
        for command, description in SLASH_COMMANDS.items():
            if command.startswith(text):
                yield Completion(
                    command,
                    start_position=-len(text),
                    display=command,
                    display_meta=description,
                )


def prompt_toolkit_available() -> bool:
    return (
        PromptSession is not None
        and InMemoryHistory is not None
        and CompleteStyle is not None
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    )


def build_prompt_session():
    if not prompt_toolkit_available():
        return None
    return PromptSession(
        completer=SlashCommandCompleter(),
        complete_while_typing=True,
        complete_style=CompleteStyle.MULTI_COLUMN,
        reserve_space_for_menu=8,
        history=InMemoryHistory(),
    )


def onboarding_needed(*, config_path: Path, venv_python: Path) -> bool:
    return (not config_path.exists()) or (not venv_python.exists())


def normalize_command_line(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    if text.startswith('/'):
        text = text[1:]
    parts = shlex.split(text)
    if not parts:
        return []

    head = parts[0].lower()
    tail = parts[1:]

    aliases: dict[str, list[str]] = {
        'help': ['help'],
        '?': ['help'],
        'doctor': ['doctor'],
        'install': ['install'],
        'configure': ['configure'],
        'snippets': ['snippets'],
        'status': ['status-clients', '--compact'],
        'clients': ['doctor-clients', '--compact'],
        'mcp': ['mcp-smoke'],
        'start': ['start-api'],
        'stop': ['stop-api'],
    }

    if head == 'provider' and tail:
        return ['configure', '--provider', tail[0], *tail[1:]]
    if head == 'ui':
        args = ['start-api']
        if len(tail) >= 1:
            args.extend(['--host', tail[0]])
        if len(tail) >= 2:
            args.extend(['--port', tail[1]])
        return args
    if head in aliases:
        return [*aliases[head], *tail]
    return parts


def render_home_screen(context: InteractiveContext) -> str:
    menu_state = 'live command menu enabled' if context.prompt_menu_enabled else 'basic prompt mode'
    notes_block = ''
    if context.provider_notes:
        note_lines = '\n'.join(f'  {note}' for note in context.provider_notes)
        notes_block = f'\nProvider notes\n{note_lines}\n'
    return f'''AgentMemory Home

Shared memory runtime for AI clients and scripts.

Status
  Provider      {context.provider}
  API           http://{context.api_host}:{context.api_port}/ui
  Config        {context.config_path.name}
  Environment   {context.env_path.name}
  Shell         {menu_state}
{notes_block}

Quick actions
  /doctor       Inspect provider, config, environment, and runtime health
  /start        Start the local API
  /ui           Start the API and open the console URL
  /status       Check connected clients
  /clients      Run client diagnostics
  /snippets     Print MCP setup snippets

Tips
  Type / to open the command menu
  Use arrow keys to select and Enter to run
  Use /help for the full command reference
  Use /exit to leave the shell
'''.strip()



def shell_intro(context: InteractiveContext) -> str:
    return render_home_screen(context)


def _run_command(
    run_command: Callable[..., int],
    argv: list[str],
    stdin_text: str | None = None,
) -> int:
    if stdin_text is None:
        return run_command(argv)
    return run_command(argv, stdin_text)


def interactive_help(context: InteractiveContext) -> str:
    return f'''AgentMemory interactive shell

Slash commands
  /help                      Show this help
  /install                   Run the installer workflow
  /configure                 Configure provider or runtime settings
  /provider <name>           Quick provider switch
  /doctor                    Run diagnostics
  /start                     Start the local API
  /stop                      Stop the local API
  /ui                        Start API and print console URL
  /mcp                       Run MCP smoke test
  /status                    Show client connection status
  /clients                   Run client diagnostics
  /snippets                  Print MCP snippets
  /exit                      Exit the shell

Examples
  /provider localjson
  /configure --provider mem0 --openrouter-api-key-env OPENROUTER_API_KEY
  /start --host {context.api_host} --port {context.api_port}
  /ui
'''.strip()


def run_onboarding(
    context: InteractiveContext,
    *,
    prompt: Callable[[str], str],
    emit: Callable[[str], None],
    run_command: Callable[..., int],
) -> int:
    emit('AgentMemory onboarding')
    emit('This is the first run. I will guide you through a minimal local setup.')

    provider = prompt('Provider [mem0/localjson] (default: mem0): ').strip().lower() or 'mem0'
    if provider not in {'mem0', 'localjson'}:
        emit('Unknown provider. Falling back to mem0.')
        provider = 'mem0'

    api_host = prompt(f'API host (default: {context.api_host}): ').strip() or context.api_host
    api_port = prompt(f'API port (default: {context.api_port}): ').strip() or str(context.api_port)

    install_args = ['install', '--provider', provider, '--api-host', api_host, '--api-port', api_port]
    rc = _run_command(run_command, install_args)
    if rc != 0:
        return rc

    configure_args = ['configure', '--provider', provider, '--api-host', api_host, '--api-port', api_port]
    configure_stdin: str | None = None
    if provider == 'mem0':
        key = prompt('OpenRouter API key (optional, press Enter to skip): ').strip()
        if key:
            configure_args.append('--openrouter-api-key-stdin')
            configure_stdin = key
    rc = _run_command(run_command, configure_args, configure_stdin)
    if rc != 0:
        return rc

    start_now = prompt('Start the API now? [Y/n]: ').strip().lower()
    if start_now in {'', 'y', 'yes'}:
        rc = _run_command(run_command, ['start-api', '--host', api_host, '--port', api_port])
        if rc == 0:
            emit(f'Console URL: http://{api_host}:{api_port}/ui')
    return rc

