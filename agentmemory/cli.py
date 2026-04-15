import argparse
import json
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from agentmemory.guidance import client_runtime_guidance, guidance_summary_lines, provider_guidance
from agentmemory.interactive import (
    InteractiveContext,
    build_prompt_session,
    interactive_help,
    render_home_screen,
    normalize_command_line,
    onboarding_needed,
    run_onboarding,
    shell_intro,
)
from agentmemory.platform import is_windows, launcher_command, launcher_path, shell_command, venv_python_path
from agentmemory.runtime.config import (
    API_PID_FILE,
    BASE_DIR,
    CONFIG_PATH,
    ENV_PATH,
    api_health_payload,
    create_profile,
    current_profile_name,
    default_runtime_config,
    get_provider,
    listening_pid_for_api_port,
    list_profile_names,
    load_runtime_config_with_source,
    provider_class,
    provider_registry,
    remove_api_state,
    runtime_identity,
    runtime_info,
    set_active_profile,
    write_api_state,
    write_runtime_config,
)
from agentmemory.runtime.transport import capability_summary
from agentmemory.certification.certify import certification_report, certification_report_json, list_targets, list_targets_json


VENV_DIR = BASE_DIR / '.venv'
VENV_PYTHON = venv_python_path(BASE_DIR)
STOP_API = launcher_path(BASE_DIR, 'stop-agentmemory-api')
START_API = launcher_path(BASE_DIR, 'start-agentmemory-api')
MCP_SMOKE = BASE_DIR / 'scripts' / 'mcp-smoke-test.py'
MCP_SNIPPET = BASE_DIR / 'snippets' / 'claude-code.mcp.json'
GEMINI_SNIPPET = BASE_DIR / 'snippets' / 'gemini-settings-snippet.json'
CLIENTS_MODULE = 'agentmemory.clients'
API_MODULE = 'agentmemory.api'
OPS_CLI_MODULE = 'agentmemory.ops_cli'
API_LOG_FILE = BASE_DIR / 'data' / 'agentmemory-api.log'
API_ERR_FILE = BASE_DIR / 'data' / 'agentmemory-api.err.log'
PLACEHOLDER_KEYS = {'paste-your-openrouter-key-here', 'YOUR_OPENROUTER_API_KEY'}


def has_real_openrouter_key(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip()
    return bool(normalized) and normalized not in PLACEHOLDER_KEYS


def color(text: str, code: str) -> str:
    return f'\033[{code}m{text}\033[0m' if sys.stdout.isatty() else text


def ok(text: str) -> str:
    return color(f'[ok] {text}', '32')


def warn(text: str) -> str:
    return color(f'[warn] {text}', '33')


def err(text: str) -> str:
    return color(f'[err] {text}', '31')


def info(text: str) -> str:
    return color(f'[info] {text}', '36')


def heading(text: str) -> None:
    line = '=' * len(text)
    print(color(line, '36'))
    print(color(text, '36;1'))
    print(color(line, '36'))


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + '...'


def render_table(rows: list[dict[str, Any]], columns: list[tuple[str, str, int]]) -> str:
    headers = [header for header, _, _ in columns]
    widths = []
    for header, key, width in columns:
        cell_width = max([len(header)] + [len(truncate(str(row.get(key, '')), width)) for row in rows])
        widths.append(min(width, cell_width))

    def render_row(values: list[str]) -> str:
        padded = []
        for idx, value in enumerate(values):
            padded.append(truncate(value, widths[idx]).ljust(widths[idx]))
        return '  '.join(padded)

    lines = [render_row(headers), render_row(['-' * w for w in widths])]
    for row in rows:
        lines.append(render_row([str(row.get(key, '')) for _, key, _ in columns]))
    return '\n'.join(lines)


def run_clients_helper(*helper_args: str) -> tuple[int, dict[str, Any] | None, str]:
    result = run([str(VENV_PYTHON), '-m', CLIENTS_MODULE, *helper_args], check=False, capture_output=True)
    raw_output = result.stdout.strip()
    payload = None
    if raw_output:
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError:
            payload = None
    return result.returncode, payload, raw_output


def print_status_payload(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return

    rows = []
    for item in payload.get('results', []):
        details = item.get('details', '')
        if not details and item.get('path'):
            details = item['path']
        rows.append(
            {
                'target': item.get('target', ''),
                'connected': 'yes' if item.get('connected') else 'no',
                'kind': item.get('kind', 'config' if item.get('path') else 'cli'),
                'details': details,
            }
        )
    print(render_table(rows, [('Target', 'target', 18), ('Connected', 'connected', 10), ('Kind', 'kind', 10), ('Details', 'details', 90)]))


def print_doctor_payload(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return

    local_server = payload.get('local_server', {})
    status_line = ok('local MCP server smoke test passed') if local_server.get('ok') else warn('local MCP server smoke test failed')
    print(status_line)
    if local_server.get('details'):
        print(truncate(str(local_server['details']), 140))
    print()

    rows = []
    for item in payload.get('results', []):
        details = item.get('details', '')
        if not details and item.get('path'):
            details = item['path']
        rows.append(
            {
                'target': item.get('target', ''),
                'detected': 'yes' if item.get('detected', item.get('path') is not None) else 'no',
                'connected': 'yes' if item.get('connected') else 'no',
                'health': item.get('health', ''),
                'kind': item.get('kind', 'config' if item.get('path') else 'cli'),
                'details': details,
            }
        )
    print(render_table(rows, [('Target', 'target', 18), ('Detected', 'detected', 10), ('Connected', 'connected', 10), ('Health', 'health', 16), ('Kind', 'kind', 10), ('Details', 'details', 80)]))


def print_provider_guidance(guidance: list[dict[str, str]]) -> None:
    if not guidance:
        return
    print()
    print(info('Operational guidance:'))
    for item in guidance:
        marker = warn if item.get('level') == 'warn' else info
        print(marker(item['message']))


def enrich_client_payload(payload: dict[str, Any], info_payload: dict[str, Any], *, include_local_server: bool = False) -> dict[str, Any]:
    local_server_ok = None
    if include_local_server:
        local_server_ok = bool(payload.get('local_server', {}).get('ok'))
    runtime_policy = info_payload.get('runtime_policy', {'transport_mode': 'direct'})
    guidance = provider_guidance(info_payload['provider'], info_payload.get('capabilities', {}), runtime_policy)
    client_guidance = client_runtime_guidance(
        info_payload['provider'],
        info_payload.get('capabilities', {}),
        runtime_policy,
        payload.get('results', []),
        local_server_ok=local_server_ok,
    )
    return {
        **payload,
        'provider': info_payload['provider'],
        'runtime_policy': runtime_policy,
        'provider_guidance': guidance,
        'client_runtime_guidance': client_guidance,
    }


def print_status_compact(payload: dict[str, Any]) -> None:
    rows = []
    for item in payload.get('results', []):
        state = 'connected' if item.get('connected') else 'not_connected'
        if item.get('kind') != 'cli' and item.get('connected'):
            state = 'configured'
        if item.get('details') == 'not detected':
            state = 'not_detected'
        rows.append({'target': item.get('target', ''), 'state': state})
    print(render_table(rows, [('Target', 'target', 18), ('State', 'state', 16)]))


def print_doctor_compact(payload: dict[str, Any]) -> None:
    rows = [{'target': 'local-server', 'state': payload.get('local_server', {}).get('health', 'unknown')}]
    for item in payload.get('results', []):
        rows.append({'target': item.get('target', ''), 'state': item.get('health', 'unknown')})
    print(render_table(rows, [('Target', 'target', 18), ('State', 'state', 16)]))


def doctor_exit_code(payload: dict[str, Any]) -> int:
    local_ok = bool(payload.get('local_server', {}).get('ok'))
    client_issue = False
    for item in payload.get('results', []):
        detected = item.get('detected', item.get('path') is not None)
        health = item.get('health', '')
        if not detected:
            continue
        if health not in {'connected', 'configured'}:
            client_issue = True
            break

    if local_ok and not client_issue:
        return 0
    if not local_ok and not client_issue:
        return 10
    if local_ok and client_issue:
        return 20
    return 30


def load_env_file() -> dict[str, str]:
    data: dict[str, str] = {}
    if not ENV_PATH.exists():
        return data
    for raw_line in ENV_PATH.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def merged_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key, value in load_env_file().items():
        env.setdefault(key, value)
    if extra:
        env.update(extra)
    return env


def read_config() -> dict:
    return load_runtime_config_with_source()[0]


def active_provider_name_from_config(config: dict[str, Any]) -> str:
    return config.get('runtime', {}).get('provider', 'mem0')


def ensure_provider_config(config: dict[str, Any], provider_name: str) -> dict[str, Any]:
    providers = config.setdefault('providers', {})
    if provider_name not in providers:
        runtime_dir = config.get('runtime', {}).get('runtime_dir', str(BASE_DIR / 'data'))
        providers[provider_name] = provider_class(provider_name).default_provider_config(runtime_dir=runtime_dir)
    return providers[provider_name]


def default_config() -> dict:
    return default_runtime_config()


def write_config(config: dict) -> None:
    write_runtime_config(config)


def write_env(values: dict[str, str]) -> None:
    current = load_env_file()
    current.update({k: v for k, v in values.items() if v is not None})
    lines = [
        '# AgentMemory local environment',
        '# Generated by agentmemory',
    ]
    for key in sorted(current):
        lines.append(f'{key}={current[key]}')
    ENV_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def current_claude_code_snippet() -> dict[str, Any]:
    launcher = launcher_path(BASE_DIR, 'run-agentmemory-mcp')
    return {
        'mcpServers': {
            'agentmemory': {
                'type': 'stdio',
                'command': shell_command(),
                'args': launcher_command(launcher)[1:],
                'env': {
                    'OPENROUTER_API_KEY': '${OPENROUTER_API_KEY}',
                },
            }
        }
    }


def current_gemini_snippet() -> dict[str, Any]:
    launcher = launcher_path(BASE_DIR, 'run-agentmemory-mcp')
    return {
        'mcpServers': {
            'agentmemory': {
                'command': shell_command(),
                'args': launcher_command(launcher)[1:],
                'env': {
                    'OPENROUTER_API_KEY': 'YOUR_OPENROUTER_API_KEY',
                },
            }
        }
    }


def resolve_bootstrap_python(value: str | None) -> list[str]:
    if value:
        return [value]
    if Path(sys.executable).exists() and 'python' in Path(sys.executable).name.lower():
        return [sys.executable]
    if is_windows():
        return ['py', '-3.13']
    return [shutil.which('python3') or 'python3']


def apply_runtime_configuration(config: dict[str, Any], args: argparse.Namespace) -> bool:
    changed = False
    runtime = config.setdefault('runtime', {})
    if getattr(args, 'api_host', None):
        if runtime.get('api_host') != args.api_host:
            runtime['api_host'] = args.api_host
            changed = True
    if getattr(args, 'api_port', None) is not None:
        if runtime.get('api_port') != args.api_port:
            runtime['api_port'] = args.api_port
            changed = True
    return changed


def run(command: Iterable[str], *, env: dict[str, str] | None = None, check: bool = True, capture_output: bool = False) -> subprocess.CompletedProcess:
    process_env = merged_env()
    if env:
        process_env.update(env)
    process_env.setdefault('PYTHONUTF8', '1')
    return subprocess.run(
        list(command),
        check=check,
        env=process_env,
        text=True,
        encoding='utf-8',
        errors='replace',
        capture_output=capture_output,
    )


def launcher_file(script: Path, *args: str, env: dict[str, str] | None = None, capture_output: bool = False) -> subprocess.CompletedProcess:
    command = [*launcher_command(script), *args]
    return run(command, env=env, capture_output=capture_output)


def api_health_url(host: str, port: int) -> str:
    return f'http://{host}:{port}/health'


def api_is_ready(host: str, port: int, *, timeout_seconds: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(api_health_url(host, port), timeout=timeout_seconds) as response:
            return response.status == 200
    except Exception:
        return False


def can_bind_api_port(host: str, port: int) -> bool:
    try:
        with socket.create_server((host, port), backlog=1):
            return True
    except OSError:
        return False


def find_available_api_port(host: str, preferred_port: int, *, search_limit: int = 50) -> int | None:
    for candidate in range(preferred_port, preferred_port + search_limit):
        if can_bind_api_port(host, candidate):
            return candidate
    return None


def read_api_pid() -> int | None:
    if not API_PID_FILE.exists():
        return None
    try:
        return int(API_PID_FILE.read_text(encoding='ascii').strip())
    except Exception:
        return None


def process_exists(pid: int | None) -> bool:
    if not pid:
        return False
    if not is_windows():
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        proc = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}'],
            check=False,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        return str(pid) in proc.stdout
    except Exception:
        return False


def managed_api_listener_pid(host: str, port: int) -> int | None:
    listener_pid = listening_pid_for_api_port(host, port)
    if listener_pid is None:
        return None
    payload = api_health_payload(host, port, timeout_seconds=1.0)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return None
    listener_runtime = payload.get("runtime_identity")
    if not isinstance(listener_runtime, dict):
        return None
    if listener_runtime.get("runtime_id") != runtime_identity().get("runtime_id"):
        return None
    return listener_pid


def start_api_process(host: str, port: int) -> tuple[bool, str]:
    API_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing_pid = read_api_pid()
    if existing_pid and process_exists(existing_pid) and api_is_ready(host, port, timeout_seconds=1.0):
        return True, f'AgentMemory API is already running with PID {existing_pid} on {api_health_url(host, port).removesuffix("/health")}'

    adopted_pid = managed_api_listener_pid(host, port)
    if adopted_pid is not None:
        API_PID_FILE.write_text(str(adopted_pid), encoding='ascii')
        write_api_state(pid=adopted_pid, host=host, port=port)
        return True, f'AgentMemory API is already running with PID {adopted_pid} on {api_health_url(host, port).removesuffix("/health")} (adopted existing runtime listener).'

    if existing_pid and process_exists(existing_pid):
        stop_api_process()

    env = merged_env({
        'AGENTMEMORY_API_HOST': host,
        'AGENTMEMORY_API_PORT': str(port),
        'AGENTMEMORY_OWNER_PROCESS': '1',
        'PYTHONUTF8': '1',
    })
    stdout_handle = API_LOG_FILE.open('w', encoding='utf-8')
    stderr_handle = API_ERR_FILE.open('w', encoding='utf-8')
    creationflags = 0
    if is_windows():
        creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) | getattr(subprocess, 'DETACHED_PROCESS', 0)
    try:
        process = subprocess.Popen(
            [str(VENV_PYTHON), '-m', API_MODULE],
            cwd=str(BASE_DIR),
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=creationflags,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()

    spinner_frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    use_spinner = sys.stdout.isatty()
    for tick in range(40):
        if use_spinner:
            frame = spinner_frames[tick % len(spinner_frames)]
            print(f'\r  {frame} Starting API on http://{host}:{port}...', end='', flush=True)
        time.sleep(0.25)
        if api_is_ready(host, port, timeout_seconds=1.0):
            if use_spinner:
                print('\r' + ' ' * 60 + '\r', end='', flush=True)
            listener_pid = listening_pid_for_api_port(host, port) or process.pid
            API_PID_FILE.write_text(str(listener_pid), encoding='ascii')
            write_api_state(pid=listener_pid, host=host, port=port)
            return True, f'AgentMemory API started with PID {listener_pid} on http://{host}:{port}. Logs: {API_LOG_FILE}, {API_ERR_FILE}'

    if use_spinner:
        print('\r' + ' ' * 60 + '\r', end='', flush=True)

    API_PID_FILE.unlink(missing_ok=True)
    remove_api_state()
    error_text = ''
    if API_ERR_FILE.exists():
        error_text = API_ERR_FILE.read_text(encoding='utf-8', errors='replace').strip()
    if not error_text and API_LOG_FILE.exists():
        error_text = API_LOG_FILE.read_text(encoding='utf-8', errors='replace').strip()
    if not error_text and process.poll() is not None:
        error_text = f'API launcher process exited before readiness (pid {process.pid}).'
    details = f' {error_text}' if error_text else ''
    return False, f'AgentMemory API failed to start on http://{host}:{port}.{details}'


def stop_api_process() -> tuple[bool, str]:
    pid = read_api_pid()
    if not pid:
        adopted_pid = managed_api_listener_pid(load_runtime_config_with_source()[0]["runtime"].get("api_host", "127.0.0.1"), load_runtime_config_with_source()[0]["runtime"].get("api_port", 8765))
        if adopted_pid is None:
            remove_api_state()
            return True, 'AgentMemory API PID file not found.'
        pid = adopted_pid
        API_PID_FILE.write_text(str(pid), encoding='ascii')
    if not process_exists(pid):
        API_PID_FILE.unlink(missing_ok=True)
        remove_api_state()
        return True, 'AgentMemory API process is not running.'

    if is_windows():
        result = subprocess.run(
            ['taskkill', '/PID', str(pid), '/F'],
            check=False,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        success = result.returncode == 0
        details = (result.stderr or result.stdout or f'Failed to stop AgentMemory API process {pid}').strip()
    else:
        try:
            os.kill(pid, signal.SIGTERM)
            success = True
            details = f'Stopped AgentMemory API process {pid}'
        except OSError as exc:
            success = False
            details = str(exc)
    API_PID_FILE.unlink(missing_ok=True)
    remove_api_state()
    if success:
        return True, f'Stopped AgentMemory API process {pid}'
    return False, details


def resolve_api_start_port(host: str, requested_port: int) -> tuple[int | None, str | None]:
    if can_bind_api_port(host, requested_port):
        return requested_port, None
    selected_port = find_available_api_port(host, requested_port + 1)
    if selected_port is None:
        return None, f'Port {requested_port} is busy and no free port was found near it.'
    return selected_port, f'Port {requested_port} is busy; using {selected_port} instead and updating runtime config.'


def persist_runtime_api_port(port: int) -> None:
    config = read_config()
    runtime = config.setdefault('runtime', {})
    if runtime.get('api_port') == port:
        return
    runtime['api_port'] = port
    write_config(config)


def command_profile_list(_: argparse.Namespace) -> int:
    heading('AgentMemory Profiles')
    active = current_profile_name()
    for profile_name in list_profile_names():
        marker = '*' if profile_name == active else ' '
        print(f'{marker} {profile_name}')
    return 0


def command_profile_create(args: argparse.Namespace) -> int:
    heading('AgentMemory Profiles')
    profile = create_profile(args.name, copy_from=args.copy_from)
    print(ok(f"Created profile '{args.name}'"))
    print(json.dumps(profile, ensure_ascii=True, indent=2))
    return 0


def command_profile_use(args: argparse.Namespace) -> int:
    heading('AgentMemory Profiles')
    set_active_profile(args.name)
    print(ok(f"Active profile: {args.name}"))
    return 0


def command_install(args: argparse.Namespace) -> int:
    heading('AgentMemory Install')
    (BASE_DIR / 'data').mkdir(exist_ok=True)
    bootstrap = resolve_bootstrap_python(args.python)
    install_config = read_config() if CONFIG_PATH.exists() and not args.rewrite_config else default_config()
    provider_changed = False
    if args.provider:
        provider_changed = install_config.get('runtime', {}).get('provider') != args.provider
        install_config['runtime']['provider'] = args.provider
        ensure_provider_config(install_config, args.provider)
    apply_runtime_configuration(install_config, args)
    active_provider = provider_class(install_config['runtime']['provider'])

    if not VENV_PYTHON.exists() or args.recreate_venv:
        if args.recreate_venv and VENV_DIR.exists():
            print(warn(f'Removing existing venv at {VENV_DIR}'))
            shutil.rmtree(VENV_DIR, ignore_errors=True)
        print(info(f"Creating virtual environment with {' '.join(bootstrap)}"))
        run([*bootstrap, '-m', 'venv', str(VENV_DIR)])
        print(ok(f'Virtual environment ready: {VENV_DIR}'))
    else:
        print(ok(f'Virtual environment already exists: {VENV_DIR}'))

    print(info('Ensuring pip is available'))
    run([str(VENV_PYTHON), '-m', 'ensurepip', '--upgrade'])

    if not args.skip_pip:
        requirements = active_provider.install_requirements()
        if requirements:
            print(info(f"Installing provider dependencies for {active_provider.display_name}: {' '.join(requirements)}"))
            run([str(VENV_PYTHON), '-m', 'pip', 'install', '--upgrade', 'pip', *requirements])
            print(ok(f'Installed provider dependencies for {active_provider.display_name}'))
        else:
            print(info(f'No extra provider dependencies declared for {active_provider.display_name}'))
    else:
        print(warn('Skipped pip installation by request'))

    if not CONFIG_PATH.exists() or args.rewrite_config or provider_changed:
        config_to_write = install_config if not args.rewrite_config else default_config()
        write_config(config_to_write)
        print(ok(f'Wrote config: {CONFIG_PATH}'))
    else:
        print(ok(f'Config already exists: {CONFIG_PATH}'))

    if not ENV_PATH.exists():
        write_env({'OPENROUTER_API_KEY': 'paste-your-openrouter-key-here'})
        print(warn(f'Created placeholder env file: {ENV_PATH}'))
    else:
        print(ok(f'Env file already exists: {ENV_PATH}'))

    print()
    print(info('Next step:'))
    print(f'  {ENV_PATH}')
    print('  Put provider credentials in .env if needed, then run `agentmemory doctor`.')
    return 0


def command_configure(args: argparse.Namespace) -> int:
    heading('AgentMemory Configure')
    config = read_config()
    provider_name = args.provider or active_provider_name_from_config(config)
    provider_switched = config.get('runtime', {}).get('provider') != provider_name
    if provider_switched:
        config['runtime']['provider'] = provider_name
    provider_config = ensure_provider_config(config, provider_name)
    provider_type = provider_class(provider_name)
    runtime_changed = apply_runtime_configuration(config, args)
    provider_config_changed = provider_type.apply_cli_configuration(provider_config=provider_config, args=args)
    changed = provider_switched or runtime_changed or provider_config_changed
    if changed:
        write_config(config)
        print(ok(f'Updated config: {CONFIG_PATH}'))
    else:
        print(info('No config fields changed'))

    env_updates = provider_type.env_updates_from_args(args)
    if env_updates:
        write_env(env_updates)
        print(ok(f'Updated provider environment in {ENV_PATH}'))

    runtime = config.get("runtime", {})
    print(info(f'Provider:  {runtime.get("provider", "unknown")}'))
    print(info(f'API:       http://{runtime.get("api_host", "127.0.0.1")}:{runtime.get("api_port", 8765)}'))
    print(info(f'Data dir:  {runtime.get("runtime_dir", "")}'))
    return 0


def command_help(_: argparse.Namespace) -> int:
    context = InteractiveContext(
        config_path=CONFIG_PATH,
        env_path=ENV_PATH,
        venv_python=VENV_PYTHON,
        api_host=runtime_info().get('api_host', '127.0.0.1'),
        api_port=runtime_info().get('api_port', 8765),
    )
    print(interactive_help(context))
    return 0


def command_list_scopes(args: argparse.Namespace) -> int:
    heading('AgentMemory Scope Inventory')
    result = run(
        [
            str(VENV_PYTHON),
            '-m',
            OPS_CLI_MODULE,
            'list-scopes',
            '--limit',
            str(args.limit),
            *(['--kind', args.kind] if args.kind else []),
            *(['--query', args.query] if args.query else []),
        ],
        check=False,
        capture_output=True,
        env=merged_env(),
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode


def command_doctor(_: argparse.Namespace) -> int:
    heading('AgentMemory Doctor')
    config_source = load_runtime_config_with_source()[1]
    info_payload = runtime_info()
    provider = get_provider()

    section = lambda title: print(f'\n  {color(title, "1")}')

    section('Environment')
    print(ok(f'Project directory: {BASE_DIR}'))
    print(ok(f"Active config: {info_payload['config_path']}"))
    if ENV_PATH.exists():
        print(ok(f'Env file: {ENV_PATH}'))
    else:
        print(info(f'Env file: not present at {ENV_PATH}'))
    print(ok(f'Virtual environment: {VENV_PYTHON}' if VENV_PYTHON.exists() else f'Virtual environment missing: {VENV_PYTHON}'))

    section('Runtime')
    print(info(f"Provider: {info_payload['provider']}"))
    print(info(f"Profile: {info_payload.get('active_profile', 'default')} (source: {config_source})"))
    print(info(f"Runtime id: {info_payload.get('runtime_identity', {}).get('runtime_id', 'unknown')}"))

    section('API')
    api_status = info_payload.get('api_runtime', {}).get('status', 'unknown')
    api_pid = info_payload.get('api_runtime', {}).get('recorded_pid', 'none')
    print(info(f"Endpoint: http://{info_payload['api_host']}:{info_payload['api_port']}"))
    print(info(f"Status: {api_status}") if api_status in ('running', 'available') else warn(f"Status: {api_status}"))
    if api_pid and api_pid != 'none':
        print(info(f"PID: {api_pid}"))

    section('Capabilities')
    capabilities = capability_summary(info_payload.get('capabilities', {}))
    print(info(f"Search: {capabilities['search_mode']}, filters: {capabilities['supports_filters']}, rerank: {capabilities['supports_rerank']}"))
    print(info(f"Scope required: search={capabilities['requires_scope_for_search']}, list={capabilities['requires_scope_for_list']}"))
    print(info(f"Transport: {info_payload.get('runtime_policy', {}).get('transport_mode', 'direct')}, contract: {info_payload.get('provider_contract', {}).get('contract_version', 'unknown')}"))
    print_provider_guidance(
        provider_guidance(
            info_payload['provider'],
            info_payload.get('capabilities', {}),
            info_payload.get('runtime_policy', {'transport_mode': 'direct'}),
        )
    )
    for prerequisite in provider.prerequisite_checks():
        if prerequisite['ok'] == 'true':
            print(ok(f"{prerequisite['name']}: {prerequisite['details']}"))
        else:
            print(warn(f"{prerequisite['name']}: {prerequisite['details']}"))
    for label, value in provider.doctor_rows():
        print(info(f'{label}: {value}'))

    if VENV_PYTHON.exists():
        for dependency in provider.dependency_checks():
            if dependency['ok'] == 'true':
                print(ok(f"{dependency['name']} installed: {dependency['details']}"))
            else:
                print(warn(f"{dependency['name']} is not installed in the venv"))
    else:
        print(warn('Skipped provider dependency checks because the venv is missing'))

    if VENV_PYTHON.exists():
        result = run([str(VENV_PYTHON), '-m', OPS_CLI_MODULE, 'health'], check=False, capture_output=True, env=merged_env())
        if result.returncode == 0:
            print(ok('AgentMemory health command works'))
        else:
            print(warn('AgentMemory health command failed'))
            if result.stderr.strip():
                print(result.stderr.strip())

    print()
    print(info('Suggested next commands:'))
    print('  /configure')
    print('  /start')
    print('  /mcp')
    return 0


def command_start_api(args: argparse.Namespace) -> int:
    heading('AgentMemory API')
    selected_port, port_message = resolve_api_start_port(args.host, args.port)
    if selected_port is None:
        print(err(port_message or f'Unable to start AgentMemory API on {args.host}:{args.port}.'))
        return 1
    updated_config_port = False
    if selected_port != args.port:
        persist_runtime_api_port(selected_port)
        updated_config_port = True
        print(warn(port_message or f'Using alternate API port {selected_port}.'))
    ok_result, message = start_api_process(args.host, selected_port)
    if not ok_result and updated_config_port:
        persist_runtime_api_port(args.port)
    print(ok(message) if ok_result else err(message))
    return 0 if ok_result else 1


def command_stop_api(_: argparse.Namespace) -> int:
    heading('AgentMemory API')
    ok_result, message = stop_api_process()
    print(ok(message) if ok_result else err(message))
    return 0 if ok_result else 1


def command_mcp_smoke(_: argparse.Namespace) -> int:
    heading('AgentMemory MCP Smoke Test')
    if not VENV_PYTHON.exists():
        print(err('Venv is missing. Run `agentmemory install` first.'))
        return 1
    result = run([str(VENV_PYTHON), str(MCP_SMOKE)], check=False, capture_output=True, env=merged_env())
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


def command_snippets(_: argparse.Namespace) -> int:
    heading('AgentMemory Snippets')
    print(ok(f'Claude Code MCP snippet: {MCP_SNIPPET}'))
    print(ok(f'Gemini CLI snippet: {GEMINI_SNIPPET}'))
    print()
    print(info('Claude Code snippet'))
    print(json.dumps(current_claude_code_snippet(), ensure_ascii=True, indent=2))
    print()
    print(info('Gemini CLI snippet'))
    print(json.dumps(current_gemini_snippet(), ensure_ascii=True, indent=2))
    return 0


def command_connect_clients(_: argparse.Namespace) -> int:
    heading('AgentMemory Client Auto-Connect')
    result_code, payload, raw_output = run_clients_helper('connect')
    if payload is not None:
        info_payload = runtime_info()
        payload = enrich_client_payload(payload, info_payload)
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        print_provider_guidance(payload['provider_guidance'])
        print_provider_guidance(payload['client_runtime_guidance'])
        return result_code
    if raw_output:
        print(raw_output)
    return result_code


def command_disconnect_clients(_: argparse.Namespace) -> int:
    heading('AgentMemory Client Disconnect')
    result = run([str(VENV_PYTHON), '-m', CLIENTS_MODULE, 'disconnect'], check=False, capture_output=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


def command_status_clients(args: argparse.Namespace) -> int:
    heading('AgentMemory Client Status')
    result_code, payload, raw_output = run_clients_helper('status')
    if payload is not None:
        info_payload = runtime_info()
        payload = enrich_client_payload(payload, info_payload)
        if args.json:
            print_status_payload(payload, as_json=True)
        elif args.compact:
            print_status_compact(payload)
            print_provider_guidance(payload['provider_guidance'])
            print_provider_guidance(payload['client_runtime_guidance'])
        else:
            print_status_payload(payload, as_json=False)
            print_provider_guidance(payload['provider_guidance'])
            print_provider_guidance(payload['client_runtime_guidance'])
    elif raw_output:
        print(raw_output)
    return result_code


def command_doctor_clients(args: argparse.Namespace) -> int:
    heading('AgentMemory Client Doctor')
    result_code, payload, raw_output = run_clients_helper('doctor')
    if payload is not None:
        info_payload = runtime_info()
        payload = enrich_client_payload(payload, info_payload, include_local_server=True)
        if args.json:
            print_doctor_payload(payload, as_json=True)
        elif args.compact:
            print_doctor_compact(payload)
            print_provider_guidance(payload['provider_guidance'])
            print_provider_guidance(payload['client_runtime_guidance'])
        else:
            print_doctor_payload(payload, as_json=False)
            print_provider_guidance(payload['provider_guidance'])
            print_provider_guidance(payload['client_runtime_guidance'])
        return doctor_exit_code(payload)
    elif raw_output:
        print(raw_output)
    return result_code


def command_provider_certify(args: argparse.Namespace) -> int:
    if args.list:
        return list_targets_json() if args.json else list_targets()
    if not args.provider:
        print(err('provider is required unless --list is used'))
        return 2
    return (
        certification_report_json(args.provider, run_tests=args.run_tests, summary_only=args.summary_only)
        if args.json
        else certification_report(args.provider, run_tests=args.run_tests, summary_only=args.summary_only)
    )


def build_parser() -> argparse.ArgumentParser:
    runtime_defaults = runtime_info()
    default_host = runtime_defaults.get('api_host', '127.0.0.1')
    default_port = int(runtime_defaults.get('api_port', 8765))
    parser = argparse.ArgumentParser(
        prog='agentmemory',
        description='Interactive shared-memory runtime for AI clients, with onboarding, slash commands, and automation-friendly subcommands.',
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    install_parser = subparsers.add_parser('install', help='Create or refresh the local venv and install the current provider dependencies.')
    install_parser.add_argument('--python', help='Bootstrap Python executable to use for venv creation.')
    install_parser.add_argument('--provider', choices=sorted(provider_registry().keys()), help='Select the active provider for the generated config.')
    install_parser.add_argument('--api-host', help='Set the default API bind host in the runtime config.')
    install_parser.add_argument('--api-port', type=int, help='Set the default API port in the runtime config.')
    install_parser.add_argument('--skip-pip', action='store_true', help='Skip pip install/upgrade after ensuring the venv.')
    install_parser.add_argument('--recreate-venv', action='store_true', help='Recreate the venv from scratch.')
    install_parser.add_argument('--rewrite-config', action='store_true', help='Rewrite the preferred generic runtime config with defaults.')
    install_parser.set_defaults(func=command_install)

    configure_parser = subparsers.add_parser('configure', help='Update provider settings and local .env values.')
    configure_parser.add_argument('--provider', choices=sorted(provider_registry().keys()), help='Switch the active provider and apply provider-specific settings.')
    configure_parser.add_argument('--api-host', help='Update the default API bind host in the runtime config.')
    configure_parser.add_argument('--api-port', type=int, help='Update the default API port in the runtime config.')
    for provider_type in provider_registry().values():
        provider_type.configure_parser(configure_parser)
    configure_parser.set_defaults(func=command_configure)

    help_parser = subparsers.add_parser('help', help='Show interactive shell help and slash commands.')
    help_parser.set_defaults(func=command_help)

    profile_list_parser = subparsers.add_parser('profile-list', help='List known AgentMemory runtime profiles.')
    profile_list_parser.set_defaults(func=command_profile_list)

    profile_create_parser = subparsers.add_parser('profile-create', help='Create a new AgentMemory runtime profile.')
    profile_create_parser.add_argument('name')
    profile_create_parser.add_argument('--copy-from', help='Clone settings from an existing profile.')
    profile_create_parser.set_defaults(func=command_profile_create)

    profile_use_parser = subparsers.add_parser('profile-use', help='Switch the active AgentMemory runtime profile.')
    profile_use_parser.add_argument('name')
    profile_use_parser.set_defaults(func=command_profile_use)

    list_scopes_parser = subparsers.add_parser('list-scopes', help='List known user, agent, and run scopes for the active provider.')
    list_scopes_parser.add_argument('--limit', type=int, default=200)
    list_scopes_parser.add_argument('--kind', choices=['user', 'agent', 'run'])
    list_scopes_parser.add_argument('--query')
    list_scopes_parser.set_defaults(func=command_list_scopes)

    doctor_parser = subparsers.add_parser('doctor', help='Check venv, config, key availability, and health.')
    doctor_parser.set_defaults(func=command_doctor)

    start_api_parser = subparsers.add_parser('start-api', help='Start the local shared memory HTTP API.')
    start_api_parser.add_argument('--host', default=default_host)
    start_api_parser.add_argument('--port', type=int, default=default_port)
    start_api_parser.set_defaults(func=command_start_api)

    stop_api_parser = subparsers.add_parser('stop-api', help='Stop the local shared memory HTTP API.')
    stop_api_parser.set_defaults(func=command_stop_api)

    mcp_parser = subparsers.add_parser('mcp-smoke', help='Run an MCP initialize/tools/list/tools/call smoke test.')
    mcp_parser.set_defaults(func=command_mcp_smoke)

    snippets_parser = subparsers.add_parser('snippets', help='Print ready-to-use Claude Code and Gemini CLI snippets.')
    snippets_parser.set_defaults(func=command_snippets)
    connect_parser = subparsers.add_parser('connect-clients', help='Auto-connect AgentMemory to detected AI clients and editors.')
    connect_parser.set_defaults(func=command_connect_clients)
    disconnect_parser = subparsers.add_parser('disconnect-clients', help='Remove AgentMemory from supported AI clients and editors.')
    disconnect_parser.set_defaults(func=command_disconnect_clients)
    status_parser = subparsers.add_parser('status-clients', help='Show AgentMemory connection status across supported AI clients and editors.')
    status_format = status_parser.add_mutually_exclusive_group()
    status_format.add_argument('--json', action='store_true', help='Emit machine-readable JSON.')
    status_format.add_argument('--table', action='store_true', help='Emit a human-readable table.')
    status_format.add_argument('--compact', action='store_true', help='Emit a short summary table.')
    status_parser.set_defaults(func=command_status_clients)
    doctor_clients_parser = subparsers.add_parser('doctor-clients', help='Check client detection, configuration state, and local MCP server health.')
    doctor_clients_format = doctor_clients_parser.add_mutually_exclusive_group()
    doctor_clients_format.add_argument('--json', action='store_true', help='Emit machine-readable JSON.')
    doctor_clients_format.add_argument('--table', action='store_true', help='Emit a human-readable table.')
    doctor_clients_format.add_argument('--compact', action='store_true', help='Emit a short summary table.')
    doctor_clients_parser.set_defaults(func=command_doctor_clients)

    provider_certify_parser = subparsers.add_parser('provider-certify', help='Assess provider certification status and optionally run provider-related tests.')
    provider_certify_parser.add_argument('provider', nargs='?', help='Provider name token, for example: localjson or mem0')
    provider_certify_parser.add_argument('--list', action='store_true', help='List known certification targets from the provider certification registry.')
    provider_certify_parser.add_argument('--json', action='store_true', help='Emit machine-readable JSON output.')
    provider_certify_parser.add_argument('--run-tests', action='store_true', help='Also run the registered certification-related test modules for the provider.')
    provider_certify_parser.add_argument('--summary-only', action='store_true', help='Show only the certification verdict and test summary without the detailed test log.')
    provider_certify_parser.set_defaults(func=command_provider_certify)

    return parser


def run_command_argv(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def interactive_input(prompt_text: str, session=None, *, interrupt_returns_exit: bool = False) -> str:
    try:
        if session is not None:
            return session.prompt(prompt_text)
        return input(prompt_text)
    except EOFError:
        return '/exit'
    except KeyboardInterrupt:
        print()
        return '/exit' if interrupt_returns_exit else ''


def current_context(*, prompt_menu_enabled: bool = False) -> InteractiveContext:
    info_payload = runtime_info()
    return InteractiveContext(
        config_path=CONFIG_PATH,
        env_path=ENV_PATH,
        venv_python=VENV_PYTHON,
        api_host=info_payload.get('api_host', '127.0.0.1'),
        api_port=info_payload.get('api_port', 8765),
        provider=info_payload.get('provider', 'mem0'),
        provider_notes=guidance_summary_lines(
            info_payload.get('provider', 'mem0'),
            info_payload.get('capabilities', {}),
            info_payload.get('runtime_policy', {'transport_mode': 'direct'}),
        ),
        prompt_menu_enabled=prompt_menu_enabled,
    )


def run_interactive_shell() -> int:
    heading('AgentMemory')
    session = build_prompt_session()
    context = current_context(prompt_menu_enabled=session is not None)

    if onboarding_needed(config_path=context.config_path, venv_python=context.venv_python):
        rc = run_onboarding(
            context,
            prompt=lambda text: interactive_input(text, session=session, interrupt_returns_exit=True),
            emit=print,
            run_command=run_command_argv,
        )
        if rc != 0:
            return rc
        context = current_context(prompt_menu_enabled=session is not None)

    print(render_home_screen(context))


    while True:
        raw = interactive_input('agentmemory> ', session=session)
        if not raw.strip():
            continue
        lowered = raw.strip().lower()
        if lowered in {'/exit', '/quit', 'exit', 'quit'}:
            print(info('Session ended.'))
            return 0

        argv = normalize_command_line(raw)
        if not argv:
            continue

        try:
            rc = run_command_argv(argv)
        except SystemExit as exc:
            rc = int(exc.code) if isinstance(exc.code, int) else 1
        except KeyboardInterrupt:
            print()
            rc = 130

        if rc not in {0, None}:
            print(warn(f'Command exited with code {rc}'))


def main() -> int:
    if len(sys.argv) == 1:
        return run_interactive_shell()
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())

