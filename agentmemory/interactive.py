from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.shortcuts import CompleteStyle
except Exception:  # pragma: no cover
    PromptSession = None
    Completion = None
    Completer = object  # type: ignore[assignment]
    FileHistory = None
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
    '/list': 'List memories for a scope',
    '/search': 'Search memories',
    '/add': 'Store a new memory',
    '/get': 'Get a memory by ID',
    '/scope': 'Set, show, or clear session scope',
    '/scopes': 'List known scopes',
    '/health': 'Show runtime health',
    '/doctor': 'Run full diagnostics',
    '/start': 'Start the local API',
    '/stop': 'Stop the local API',
    '/configure': 'Configure provider or runtime',
    '/provider': 'Quick provider switch',
    '/ui': 'Start API and print console URL',
    '/status': 'Show client connection status',
    '/snippets': 'Print MCP snippets',
    '/install': 'Run the installer workflow',
    '/mcp': 'Run MCP smoke test',
    '/clients': 'Run client diagnostics',
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
        and FileHistory is not None
        and CompleteStyle is not None
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    )


def _history_path() -> Path:
    return Path.home() / ".agentmemory_history"


def build_prompt_session():
    if not prompt_toolkit_available():
        return None
    return PromptSession(
        completer=SlashCommandCompleter(),
        complete_while_typing=True,
        complete_style=CompleteStyle.MULTI_COLUMN,
        reserve_space_for_menu=8,
        history=FileHistory(str(_history_path())),
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
        'health': ['health'],
        'install': ['install'],
        'configure': ['configure'],
        'snippets': ['snippets'],
        'status': ['status-clients', '--compact'],
        'clients': ['doctor-clients', '--compact'],
        'mcp': ['mcp-smoke'],
        'start': ['start-api'],
        'stop': ['stop-api'],
        'list': ['list'],
        'search': ['search'],
        'add': ['add'],
        'get': ['get'],
        'update': ['update'],
        'delete': ['delete'],
        'scopes': ['list-scopes'],
    }

    if head == 'scope':
        if not tail:
            return ['scope', 'show']
        sub = tail[0].lower()
        if sub in {'set', 'show', 'clear'}:
            return ['scope', sub, *tail[1:]]
        # /scope alice → scope set --user-id alice
        return ['scope', 'set', '--user-id', tail[0], *tail[1:]]
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
    is_tty = sys.stdout.isatty()

    def _c(code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if is_tty else text

    bold = lambda t: _c("1", t)
    dim = lambda t: _c("2", t)
    green = lambda t: _c("32", t)
    cyan = lambda t: _c("36", t)
    yellow = lambda t: _c("33", t)

    notes_block = ''
    if context.provider_notes:
        note_lines = '\n'.join(f'  {yellow("›")} {note}' for note in context.provider_notes)
        notes_block = f'\n{note_lines}\n'

    api_url = f'http://{context.api_host}:{context.api_port}'
    menu_label = green('● enabled') if context.prompt_menu_enabled else dim('○ basic mode')

    return f'''{bold("AgentMemory")}  {dim("shared memory runtime")}

{"╭─ Status ──────────────────────────────────────────╮" if is_tty else "Status"}
{"│" if is_tty else ""}  Provider    {cyan(context.provider)}
{"│" if is_tty else ""}  API         {api_url}/ui
{"│" if is_tty else ""}  Config      {context.config_path.name}
{"│" if is_tty else ""}  Completions {menu_label}
{"╰──────────────────────────────────────────────────╯" if is_tty else ""}{notes_block}
{bold("Memory")}
  {cyan("/list")}       List memories          {cyan("/search")} {dim("<query>")}  Search
  {cyan("/add")}        Store a new memory     {cyan("/get")} {dim("<id>")}      Get by ID
  {cyan("/scopes")}     List known scopes      {cyan("/health")}          Runtime status

{bold("Admin")}
  {cyan("/doctor")}     Run diagnostics        {cyan("/start")}           Start API
  {cyan("/configure")}  Configure provider     {cyan("/snippets")}        MCP snippets

{dim("Type / to open the command menu · /exit to leave")}'''.strip()



def shell_intro(context: InteractiveContext) -> str:
    return render_home_screen(context)
def interactive_help(context: InteractiveContext) -> str:
    return f'''AgentMemory interactive shell

Memory commands
  /list                                List memories (add --user-id to filter)
  /search <query>                      Search memories
  /add --message "<text>" --user-id u  Store a new memory
  /get <memory-id>                     Get one memory by ID
  /scopes                              List known user/agent/run scopes
  /health                              Show runtime health status

Admin commands
  /doctor                              Run full diagnostics
  /configure                           Configure provider or runtime settings
  /provider <name>                     Quick provider switch
  /start                               Start the local API
  /stop                                Stop the local API
  /ui                                  Start API and print console URL
  /status                              Show client connection status
  /snippets                            Print MCP setup snippets
  /mcp                                 Run MCP smoke test
  /install                             Run the installer workflow
  /exit                                Exit the shell

Examples
  /list --user-id alice
  /search "dark mode" --user-id alice
  /add --message "prefers dark mode" --user-id alice
  /provider localjson
  /start --host {context.api_host} --port {context.api_port}
'''.strip()


def run_onboarding(
    context: InteractiveContext,
    *,
    prompt: Callable[[str], str],
    emit: Callable[[str], None],
    run_command: Callable[[list[str]], int],
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
    rc = run_command(install_args)
    if rc != 0:
        return rc

    configure_args = ['configure', '--provider', provider, '--api-host', api_host, '--api-port', api_port]
    if provider == 'mem0':
        key = prompt('OpenRouter API key (optional, press Enter to skip): ').strip()
        if key:
            configure_args.extend(['--openrouter-api-key', key])
    rc = run_command(configure_args)
    if rc != 0:
        return rc

    start_now = prompt('Start the API now? [Y/n]: ').strip().lower()
    if start_now in {'', 'y', 'yes'}:
        rc = run_command(['start-api', '--host', api_host, '--port', api_port])
        if rc == 0:
            emit(f'Console URL: http://{api_host}:{api_port}/ui')
    return rc

