import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from agentmemory_platform import is_windows, launcher_command, launcher_path, shell_command, venv_python_path
from agentmemory_runtime import (
    CONFIG_PATH,
    ENV_PATH,
    default_runtime_config,
    get_provider,
    load_runtime_config_with_source,
    provider_class,
    provider_registry,
    runtime_info,
    write_runtime_config,
)


BASE_DIR = Path(__file__).resolve().parent
VENV_DIR = BASE_DIR / ".venv"
VENV_PYTHON = venv_python_path(BASE_DIR)
STOP_API = launcher_path(BASE_DIR, "stop-agentmemory-api")
START_API = launcher_path(BASE_DIR, "start-agentmemory-api")
MCP_SMOKE = BASE_DIR / "mcp-smoke-test.py"
MCP_SNIPPET = BASE_DIR / "claude-code.mcp.json"
GEMINI_SNIPPET = BASE_DIR / "gemini-settings-snippet.json"
CLIENTS_HELPER = BASE_DIR / "agentmemory_clients.py"
PLACEHOLDER_KEYS = {"paste-your-openrouter-key-here", "YOUR_OPENROUTER_API_KEY"}


def has_real_openrouter_key(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip()
    return bool(normalized) and normalized not in PLACEHOLDER_KEYS


def color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def ok(text: str) -> str:
    return color(f"[ok] {text}", "32")


def warn(text: str) -> str:
    return color(f"[warn] {text}", "33")


def err(text: str) -> str:
    return color(f"[err] {text}", "31")


def info(text: str) -> str:
    return color(f"[info] {text}", "36")


def heading(text: str) -> None:
    line = "=" * len(text)
    print(color(line, "36"))
    print(color(text, "36;1"))
    print(color(line, "36"))


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def render_table(rows: list[dict[str, Any]], columns: list[tuple[str, str, int]]) -> str:
    headers = [header for header, _, _ in columns]
    widths = []
    for header, key, width in columns:
        cell_width = max(
            [len(header)] + [len(truncate(str(row.get(key, "")), width)) for row in rows],
        )
        widths.append(min(width, cell_width))

    def render_row(values: list[str]) -> str:
        padded = []
        for idx, value in enumerate(values):
            padded.append(truncate(value, widths[idx]).ljust(widths[idx]))
        return "  ".join(padded)

    lines = [render_row(headers), render_row(["-" * w for w in widths])]
    for row in rows:
        lines.append(render_row([str(row.get(key, "")) for _, key, _ in columns]))
    return "\n".join(lines)


def run_clients_helper(*helper_args: str) -> tuple[int, dict[str, Any] | None, str]:
    result = run([str(VENV_PYTHON), str(CLIENTS_HELPER), *helper_args], check=False, capture_output=True)
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
    for item in payload.get("results", []):
        details = item.get("details", "")
        if not details and item.get("path"):
            details = item["path"]
        rows.append(
            {
                "target": item.get("target", ""),
                "connected": "yes" if item.get("connected") else "no",
                "kind": item.get("kind", "config" if item.get("path") else "cli"),
                "details": details,
            }
        )
    print(render_table(rows, [("Target", "target", 18), ("Connected", "connected", 10), ("Kind", "kind", 10), ("Details", "details", 90)]))


def print_doctor_payload(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return

    local_server = payload.get("local_server", {})
    status_line = ok("local MCP server smoke test passed") if local_server.get("ok") else warn("local MCP server smoke test failed")
    print(status_line)
    if local_server.get("details"):
        print(truncate(str(local_server["details"]), 140))
    print()

    rows = []
    for item in payload.get("results", []):
        details = item.get("details", "")
        if not details and item.get("path"):
            details = item["path"]
        rows.append(
            {
                "target": item.get("target", ""),
                "detected": "yes" if item.get("detected", item.get("path") is not None) else "no",
                "connected": "yes" if item.get("connected") else "no",
                "health": item.get("health", ""),
                "kind": item.get("kind", "config" if item.get("path") else "cli"),
                "details": details,
            }
        )
    print(render_table(rows, [("Target", "target", 18), ("Detected", "detected", 10), ("Connected", "connected", 10), ("Health", "health", 16), ("Kind", "kind", 10), ("Details", "details", 80)]))


def print_status_compact(payload: dict[str, Any]) -> None:
    rows = []
    for item in payload.get("results", []):
        state = "connected" if item.get("connected") else "not_connected"
        if item.get("kind") != "cli" and item.get("connected"):
            state = "configured"
        if item.get("details") == "not detected":
            state = "not_detected"
        rows.append({"target": item.get("target", ""), "state": state})
    print(render_table(rows, [("Target", "target", 18), ("State", "state", 16)]))


def print_doctor_compact(payload: dict[str, Any]) -> None:
    rows = [
        {
            "target": "local-server",
            "state": payload.get("local_server", {}).get("health", "unknown"),
        }
    ]
    for item in payload.get("results", []):
        rows.append({"target": item.get("target", ""), "state": item.get("health", "unknown")})
    print(render_table(rows, [("Target", "target", 18), ("State", "state", 16)]))


def doctor_exit_code(payload: dict[str, Any]) -> int:
    local_ok = bool(payload.get("local_server", {}).get("ok"))
    client_issue = False
    for item in payload.get("results", []):
        detected = item.get("detected", item.get("path") is not None)
        health = item.get("health", "")
        if not detected:
            continue
        if health not in {"connected", "configured"}:
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
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
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
    return config.get("runtime", {}).get("provider", "mem0")


def active_provider_config(config: dict[str, Any]) -> dict[str, Any]:
    provider_name = active_provider_name_from_config(config)
    providers = config.get("providers", {})
    if provider_name not in providers:
        raise KeyError(provider_name)
    return providers[provider_name]


def ensure_provider_config(config: dict[str, Any], provider_name: str) -> dict[str, Any]:
    providers = config.setdefault("providers", {})
    if provider_name not in providers:
        runtime_dir = config.get("runtime", {}).get("runtime_dir", str(BASE_DIR / "data"))
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
        "# AgentMemory local environment",
        "# Generated by agentmemory.py",
    ]
    for key in sorted(current):
        lines.append(f"{key}={current[key]}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def current_claude_code_snippet() -> dict[str, Any]:
    launcher = launcher_path(BASE_DIR, "run-agentmemory-mcp")
    return {
        "mcpServers": {
            "agentmemory": {
                "type": "stdio",
                "command": shell_command(),
                "args": launcher_command(launcher)[1:],
                "env": {
                    "OPENROUTER_API_KEY": "${OPENROUTER_API_KEY}",
                },
            }
        }
    }


def current_gemini_snippet() -> dict[str, Any]:
    launcher = launcher_path(BASE_DIR, "run-agentmemory-mcp")
    return {
        "mcpServers": {
            "agentmemory": {
                "command": shell_command(),
                "args": launcher_command(launcher)[1:],
                "env": {
                    "OPENROUTER_API_KEY": "YOUR_OPENROUTER_API_KEY",
                },
            }
        }
    }


def resolve_bootstrap_python(value: str | None) -> list[str]:
    if value:
        return [value]
    if Path(sys.executable).exists() and "python" in Path(sys.executable).name.lower():
        return [sys.executable]
    if is_windows():
        return ["py", "-3.13"]
    return [shutil.which("python3") or "python3"]


def apply_runtime_configuration(config: dict[str, Any], args: argparse.Namespace) -> bool:
    changed = False
    runtime = config.setdefault("runtime", {})
    if getattr(args, "api_host", None):
        if runtime.get("api_host") != args.api_host:
            runtime["api_host"] = args.api_host
            changed = True
    if getattr(args, "api_port", None) is not None:
        if runtime.get("api_port") != args.api_port:
            runtime["api_port"] = args.api_port
            changed = True
    return changed


def run(command: Iterable[str], *, env: dict[str, str] | None = None, check: bool = True, capture_output: bool = False) -> subprocess.CompletedProcess:
    process_env = merged_env()
    if env:
        process_env.update(env)
    process_env.setdefault("PYTHONUTF8", "1")
    return subprocess.run(
        list(command),
        check=check,
        env=process_env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture_output,
    )


def launcher_file(script: Path, *args: str, env: dict[str, str] | None = None, capture_output: bool = False) -> subprocess.CompletedProcess:
    command = [*launcher_command(script), *args]
    return run(command, env=env, capture_output=capture_output)


def command_install(args: argparse.Namespace) -> int:
    heading("AgentMemory Install")
    (BASE_DIR / "data").mkdir(exist_ok=True)
    bootstrap = resolve_bootstrap_python(args.python)
    install_config = read_config() if CONFIG_PATH.exists() and not args.rewrite_config else default_config()
    provider_changed = False
    if args.provider:
        provider_changed = install_config.get("runtime", {}).get("provider") != args.provider
        install_config["runtime"]["provider"] = args.provider
        ensure_provider_config(install_config, args.provider)
    apply_runtime_configuration(install_config, args)
    active_provider = provider_class(install_config["runtime"]["provider"])

    if not VENV_PYTHON.exists() or args.recreate_venv:
        if args.recreate_venv and VENV_DIR.exists():
            print(warn(f"Removing existing venv at {VENV_DIR}"))
            shutil.rmtree(VENV_DIR, ignore_errors=True)
        print(info(f"Creating virtual environment with {' '.join(bootstrap)}"))
        run([*bootstrap, "-m", "venv", str(VENV_DIR)])
        print(ok(f"Virtual environment ready: {VENV_DIR}"))
    else:
        print(ok(f"Virtual environment already exists: {VENV_DIR}"))

    print(info("Ensuring pip is available"))
    run([str(VENV_PYTHON), "-m", "ensurepip", "--upgrade"])

    if not args.skip_pip:
        requirements = active_provider.install_requirements()
        if requirements:
            print(info(f"Installing provider dependencies for {active_provider.display_name}: {' '.join(requirements)}"))
            run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip", *requirements])
            print(ok(f"Installed provider dependencies for {active_provider.display_name}"))
        else:
            print(info(f"No extra provider dependencies declared for {active_provider.display_name}"))
    else:
        print(warn("Skipped pip installation by request"))

    if not CONFIG_PATH.exists() or args.rewrite_config or provider_changed:
        config_to_write = install_config if not args.rewrite_config else default_config()
        write_config(config_to_write)
        print(ok(f"Wrote config: {CONFIG_PATH}"))
    else:
        print(ok(f"Config already exists: {CONFIG_PATH}"))

    if not ENV_PATH.exists():
        write_env({"OPENROUTER_API_KEY": "paste-your-openrouter-key-here"})
        print(warn(f"Created placeholder env file: {ENV_PATH}"))
    else:
        print(ok(f"Env file already exists: {ENV_PATH}"))

    print()
    print(info("Next step:"))
    print(f"  {ENV_PATH}")
    print("  Put provider credentials in .env if needed, then run `agentmemory doctor`.")
    return 0


def command_configure(args: argparse.Namespace) -> int:
    heading("AgentMemory Configure")
    config = read_config()
    provider_name = args.provider or active_provider_name_from_config(config)
    provider_switched = config.get("runtime", {}).get("provider") != provider_name
    if provider_switched:
        config["runtime"]["provider"] = provider_name
    provider_config = ensure_provider_config(config, provider_name)
    provider_type = provider_class(provider_name)
    changed = provider_switched or apply_runtime_configuration(config, args) or provider_type.apply_cli_configuration(provider_config=provider_config, args=args)
    if changed:
        write_config(config)
        print(ok(f"Updated config: {CONFIG_PATH}"))
    else:
        print(info("No config fields changed"))

    env_updates = provider_type.env_updates_from_args(args)
    if env_updates:
        write_env(env_updates)
        print(ok(f"Updated provider environment in {ENV_PATH}"))

    print(json.dumps(config, ensure_ascii=True, indent=2))
    return 0


def command_doctor(_: argparse.Namespace) -> int:
    heading("AgentMemory Doctor")
    config_source = load_runtime_config_with_source()[1]
    info_payload = runtime_info()
    provider = get_provider()

    print(ok(f"Project directory: {BASE_DIR}"))
    print(ok(f"Active config: {info_payload['config_path']}"))
    if ENV_PATH.exists():
        print(ok(f"Env file: {ENV_PATH}"))
    else:
        print(warn(f"Env file missing: {ENV_PATH}"))
    print(ok(f"Virtual environment: {VENV_PYTHON}" if VENV_PYTHON.exists() else f"Virtual environment missing: {VENV_PYTHON}"))

    print(info(f"Active provider: {info_payload['provider']}"))
    print(info(f"Config source: {config_source}"))
    print(info(f"API host: {info_payload['api_host']}"))
    print(info(f"API port: {info_payload['api_port']}"))
    for prerequisite in provider.prerequisite_checks():
        if prerequisite["ok"] == "true":
            print(ok(f"{prerequisite['name']}: {prerequisite['details']}"))
        else:
            print(warn(f"{prerequisite['name']}: {prerequisite['details']}"))
    for label, value in provider.doctor_rows():
        print(info(f"{label}: {value}"))

    if VENV_PYTHON.exists():
        for dependency in provider.dependency_checks():
            if dependency["ok"] == "true":
                print(ok(f"{dependency['name']} installed: {dependency['details']}"))
            else:
                print(warn(f"{dependency['name']} is not installed in the venv"))
    else:
        print(warn("Skipped provider dependency checks because the venv is missing"))

    if VENV_PYTHON.exists():
        result = run([str(VENV_PYTHON), str(BASE_DIR / "agentmemory_cli.py"), "health"], check=False, capture_output=True, env=merged_env())
        if result.returncode == 0:
            print(ok("AgentMemory health command works"))
        else:
            print(warn("AgentMemory health command failed"))
            if result.stderr.strip():
                print(result.stderr.strip())

    print()
    print(info("Suggested next commands:"))
    print("  agentmemory configure")
    print("  agentmemory start-api")
    print("  agentmemory mcp-smoke")
    return 0


def command_start_api(args: argparse.Namespace) -> int:
    heading("AgentMemory API")
    env = merged_env({"AGENTMEMORY_API_HOST": args.host, "AGENTMEMORY_API_PORT": str(args.port)})
    result = launcher_file(START_API, args.host, str(args.port), env=env, capture_output=False)
    return result.returncode


def command_stop_api(_: argparse.Namespace) -> int:
    heading("AgentMemory API")
    result = launcher_file(STOP_API, env=merged_env(), capture_output=False)
    return result.returncode


def command_mcp_smoke(_: argparse.Namespace) -> int:
    heading("AgentMemory MCP Smoke Test")
    if not VENV_PYTHON.exists():
        print(err("Venv is missing. Run `agentmemory install` first."))
        return 1
    result = run([str(VENV_PYTHON), str(MCP_SMOKE)], check=False, capture_output=True, env=merged_env())
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


def command_snippets(_: argparse.Namespace) -> int:
    heading("AgentMemory Snippets")
    print(ok(f"Claude Code MCP snippet: {MCP_SNIPPET}"))
    print(ok(f"Gemini CLI snippet: {GEMINI_SNIPPET}"))
    print()
    print(info("Claude Code snippet"))
    print(json.dumps(current_claude_code_snippet(), ensure_ascii=True, indent=2))
    print()
    print(info("Gemini CLI snippet"))
    print(json.dumps(current_gemini_snippet(), ensure_ascii=True, indent=2))
    return 0


def command_connect_clients(_: argparse.Namespace) -> int:
    heading("AgentMemory Client Auto-Connect")
    result = run([str(VENV_PYTHON), str(CLIENTS_HELPER)], check=False, capture_output=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


def command_disconnect_clients(_: argparse.Namespace) -> int:
    heading("AgentMemory Client Disconnect")
    result = run([str(VENV_PYTHON), str(CLIENTS_HELPER), "disconnect"], check=False, capture_output=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


def command_status_clients(args: argparse.Namespace) -> int:
    heading("AgentMemory Client Status")
    result_code, payload, raw_output = run_clients_helper("status")
    if payload is not None:
        if args.json:
            print_status_payload(payload, as_json=True)
        elif args.compact:
            print_status_compact(payload)
        else:
            print_status_payload(payload, as_json=False)
    elif raw_output:
        print(raw_output)
    return result_code


def command_doctor_clients(args: argparse.Namespace) -> int:
    heading("AgentMemory Client Doctor")
    result_code, payload, raw_output = run_clients_helper("doctor")
    if payload is not None:
        if args.json:
            print_doctor_payload(payload, as_json=True)
        elif args.compact:
            print_doctor_compact(payload)
        else:
            print_doctor_payload(payload, as_json=False)
        return doctor_exit_code(payload)
    elif raw_output:
        print(raw_output)
    return result_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentmemory",
        description="Product-style installer and operations CLI for the provider-based AgentMemory shared memory stack.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install", help="Create or refresh the local venv and install the current provider dependencies.")
    install_parser.add_argument("--python", help="Bootstrap Python executable to use for venv creation.")
    install_parser.add_argument("--provider", choices=sorted(provider_registry().keys()), help="Select the active provider for the generated config.")
    install_parser.add_argument("--api-host", help="Set the default API bind host in the runtime config.")
    install_parser.add_argument("--api-port", type=int, help="Set the default API port in the runtime config.")
    install_parser.add_argument("--skip-pip", action="store_true", help="Skip pip install/upgrade after ensuring the venv.")
    install_parser.add_argument("--recreate-venv", action="store_true", help="Recreate the venv from scratch.")
    install_parser.add_argument("--rewrite-config", action="store_true", help="Rewrite the preferred generic runtime config with defaults.")
    install_parser.set_defaults(func=command_install)

    configure_parser = subparsers.add_parser("configure", help="Update provider settings and local .env values.")
    configure_parser.add_argument("--provider", choices=sorted(provider_registry().keys()), help="Switch the active provider and apply provider-specific settings.")
    configure_parser.add_argument("--api-host", help="Update the default API bind host in the runtime config.")
    configure_parser.add_argument("--api-port", type=int, help="Update the default API port in the runtime config.")
    for provider_type in provider_registry().values():
        provider_type.configure_parser(configure_parser)
    configure_parser.set_defaults(func=command_configure)

    doctor_parser = subparsers.add_parser("doctor", help="Check venv, config, key availability, and health.")
    doctor_parser.set_defaults(func=command_doctor)

    start_api_parser = subparsers.add_parser("start-api", help="Start the local shared memory HTTP API.")
    start_api_parser.add_argument("--host", default="127.0.0.1")
    start_api_parser.add_argument("--port", type=int, default=8765)
    start_api_parser.set_defaults(func=command_start_api)

    stop_api_parser = subparsers.add_parser("stop-api", help="Stop the local shared memory HTTP API.")
    stop_api_parser.set_defaults(func=command_stop_api)

    mcp_parser = subparsers.add_parser("mcp-smoke", help="Run an MCP initialize/tools/list/tools/call smoke test.")
    mcp_parser.set_defaults(func=command_mcp_smoke)

    snippets_parser = subparsers.add_parser("snippets", help="Print ready-to-use Claude Code and Gemini CLI snippets.")
    snippets_parser.set_defaults(func=command_snippets)
    connect_parser = subparsers.add_parser("connect-clients", help="Auto-connect AgentMemory to detected AI clients and editors.")
    connect_parser.set_defaults(func=command_connect_clients)
    disconnect_parser = subparsers.add_parser("disconnect-clients", help="Remove AgentMemory from supported AI clients and editors.")
    disconnect_parser.set_defaults(func=command_disconnect_clients)
    status_parser = subparsers.add_parser("status-clients", help="Show AgentMemory connection status across supported AI clients and editors.")
    status_format = status_parser.add_mutually_exclusive_group()
    status_format.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    status_format.add_argument("--table", action="store_true", help="Emit a human-readable table.")
    status_format.add_argument("--compact", action="store_true", help="Emit a short summary table.")
    status_parser.set_defaults(func=command_status_clients)
    doctor_clients_parser = subparsers.add_parser("doctor-clients", help="Check client detection, configuration state, and local MCP server health.")
    doctor_clients_format = doctor_clients_parser.add_mutually_exclusive_group()
    doctor_clients_format.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    doctor_clients_format.add_argument("--table", action="store_true", help="Emit a human-readable table.")
    doctor_clients_format.add_argument("--compact", action="store_true", help="Emit a short summary table.")
    doctor_clients_parser.set_defaults(func=command_doctor_clients)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())


