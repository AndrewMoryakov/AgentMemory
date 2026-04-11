import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from agentmemory.platform import launcher_path
from agentmemory.runtime.config import BASE_DIR

RUN_MCP = launcher_path(BASE_DIR, "run-agentmemory-mcp")
SERVER_NAME = "agentmemory"
BACKUP_ROOT = BASE_DIR / "data" / "backups" / "client-configs"

CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
CLAUDE_CODE_CONFIG = Path.home() / ".claude.json"
GEMINI_SETTINGS = Path.home() / ".gemini" / "settings.json"
QWEN_SETTINGS = Path.home() / ".qwen" / "settings.json"
CURSOR_MCP = Path.home() / ".cursor" / "mcp.json"
CLAUDE_DESKTOP_CONFIG = Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
VSCODE_MCP = Path.home() / "AppData" / "Roaming" / "Code" / "User" / "mcp.json"
ROO_MCP = Path.home() / "AppData" / "Roaming" / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "mcp_settings.json"
KILO_MCP = Path.home() / "AppData" / "Roaming" / "Code" / "User" / "globalStorage" / "kilocode.kilo-code" / "settings" / "mcp_settings.json"
CLINE_VSCODE_MCP = Path.home() / "AppData" / "Roaming" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "mcp_settings.json"
CLINE_CURSOR_MCP = Path.home() / "AppData" / "Roaming" / "Cursor" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "mcp_settings.json"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def quote_ps(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def resolve_pwsh_command() -> str:
    return shutil.which("pwsh") or "pwsh"


def run_pwsh(command: str, *, timeout_seconds: float | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [resolve_pwsh_command(), "-NoLogo", "-NoProfile", "-Command", command],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=exc.cmd,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + "\nCommand timed out.",
        )


def command_result(label: str, completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "target": label,
        "returncode": completed.returncode,
        "stdout": normalize_display_text(completed.stdout),
        "stderr": normalize_display_text(completed.stderr),
    }


def normalize_display_text(text: str | None) -> str:
    if not text:
        return ""
    normalized = ANSI_RE.sub("", text)
    normalized = normalized.replace("\u2713", "[ok]").replace("\u2717", "[x]")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.strip()


def backup_file(path: Path, backup_dir: Path) -> None:
    if not path.exists():
        return
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_dir / path.name)


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default))
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def stdio_server_config() -> dict[str, Any]:
    return {
        "command": resolve_pwsh_command(),
        "args": [
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(RUN_MCP).replace("\\", "/"),
        ],
    }


def expected_launcher_path() -> str:
    return str(RUN_MCP).replace("\\", "/")


def normalize_launcher_path(value: str | None) -> str | None:
    if not value:
        return value
    normalized = value.replace("\\", "/")
    normalized = re.sub(r"^([A-Za-z]:)/+", r"\1/", normalized)
    normalized = re.sub(r"(?<!:)/{2,}", "/", normalized)
    return normalized


def config_server_details(root: dict[str, Any], server_name: str) -> dict[str, Any]:
    if not isinstance(root, dict) or server_name not in root:
        return {}
    server = root.get(server_name)
    if not isinstance(server, dict):
        return {"raw": server}

    args = server.get("args")
    launcher = ""
    if isinstance(args, list):
        for value in args:
            if isinstance(value, str) and value.lower().endswith(".ps1"):
                launcher = value.replace("\\", "/")
                break

    launcher = normalize_launcher_path(launcher)
    expected = normalize_launcher_path(expected_launcher_path())
    stale = bool(launcher) and launcher != expected
    return {
        "command": server.get("command"),
        "args": args if isinstance(args, list) else None,
        "launcher": launcher or None,
        "expected_launcher": expected,
        "stale_launcher": stale,
    }


def text_config_status(path: Path, target: str, *, kind: str = "cli") -> dict[str, Any]:
    if not path.exists():
        return {
            "target": target,
            "kind": kind,
            "connected": False,
            "configured": False,
            "details": "not detected",
            "path": str(path),
            "health": "not_detected",
        }

    raw = path.read_text(encoding="utf-8", errors="replace")
    configured = SERVER_NAME in raw
    launcher_match = re.search(r"([A-Za-z]:[/\\\\].*?(?:scripts[/\\\\])?run-(?:agentmemory|mem0)-mcp\.ps1)", raw, re.IGNORECASE)
    launcher = normalize_launcher_path(launcher_match.group(1) if launcher_match else None)
    expected = normalize_launcher_path(expected_launcher_path())
    stale = bool(launcher) and launcher != expected
    health = "configured" if configured else "not_configured"
    if configured and stale:
        health = "stale_config"
    return {
        "target": target,
        "kind": kind,
        "connected": False,
        "configured": configured,
        "details": "configured" if configured else "not configured",
        "path": str(path),
        "health": health,
        "launcher": launcher,
        "expected_launcher": expected,
        "stale_launcher": stale,
    }


def merge_server_json(path: Path, root_key: str, server_name: str, server_config: dict[str, Any], backup_dir: Path) -> dict[str, Any]:
    payload = load_json(path, {root_key: {}})
    if root_key not in payload or not isinstance(payload[root_key], dict):
        payload[root_key] = {}
    payload[root_key][server_name] = server_config
    backup_file(path, backup_dir)
    write_json(path, payload)
    return {
        "status": "updated",
        "path": str(path),
    }


def remove_server_json(path: Path, root_key: str, server_name: str, backup_dir: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "skipped", "path": str(path), "reason": "not detected"}

    payload = load_json(path, {root_key: {}})
    if root_key not in payload or not isinstance(payload[root_key], dict):
        return {"status": "skipped", "path": str(path), "reason": "missing root key"}
    if server_name not in payload[root_key]:
        return {"status": "skipped", "path": str(path), "reason": "not configured"}

    backup_file(path, backup_dir)
    del payload[root_key][server_name]
    write_json(path, payload)
    return {
        "status": "updated",
        "path": str(path),
    }


def remove_then_add(label: str, remove_cmd: str, add_cmd: str) -> dict[str, Any]:
    remove_result = run_pwsh(remove_cmd)
    add_result = run_pwsh(add_cmd)
    status = "updated" if add_result.returncode == 0 else "failed"
    return {
        "target": label,
        "status": status,
        "remove": command_result(label + ":remove", remove_result),
        "add": command_result(label + ":add", add_result),
    }


def remove_only(label: str, remove_cmd: str) -> dict[str, Any]:
    remove_result = run_pwsh(remove_cmd)
    status = "updated" if remove_result.returncode == 0 else "skipped"
    result = {
        "target": label,
        "status": status,
        "remove": command_result(label + ":remove", remove_result),
    }
    if status == "skipped":
        result["reason"] = "not configured"
    return result


def config_status(path: Path, root_key: str, target: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "target": target,
            "kind": "config",
            "connected": False,
            "configured": False,
            "details": "not detected",
            "path": str(path),
            "health": "not_detected",
        }
    payload = load_json(path, {root_key: {}})
    root = payload.get(root_key, {})
    connected = isinstance(root, dict) and SERVER_NAME in root
    server_details = config_server_details(root, SERVER_NAME)
    health = "configured" if connected else "not_configured"
    if connected and server_details.get("stale_launcher"):
        health = "stale_config"
    return {
        "target": target,
        "kind": "config",
        "connected": connected,
        "configured": connected,
        "details": "configured" if connected else "not configured",
        "path": str(path),
        "health": health,
        **server_details,
    }


def cli_status(label: str, command: str, *, timeout_seconds: float | None = None) -> dict[str, Any]:
    result = run_pwsh(command, timeout_seconds=timeout_seconds)
    output = normalize_display_text((result.stdout or "") + ("\n" + result.stderr if result.stderr else ""))
    connected = result.returncode == 0 and SERVER_NAME in output
    health = "connected" if connected else ("timeout" if result.returncode == 124 else ("not_configured" if output else "unknown"))
    return {
        "target": label,
        "kind": "cli",
        "connected": connected,
        "configured": connected,
        "health": health,
        "details": output,
    }


def cli_detected(command_name: str) -> bool:
    result = run_pwsh(f"Get-Command {quote_ps(command_name)}")
    return result.returncode == 0


def config_doctor(path: Path, root_key: str, target: str) -> dict[str, Any]:
    status = config_status(path, root_key, target)
    status["detected"] = path.exists() or path.parent.exists()
    if not status["detected"]:
        status["health"] = "not_detected"
    elif not status["configured"]:
        status["health"] = "not_configured"
    return status


def cli_doctor(label: str, command_name: str, list_command: str) -> dict[str, Any]:
    detected = cli_detected(command_name)
    if not detected:
        return {
            "target": label,
            "kind": "cli",
            "detected": False,
            "connected": False,
            "health": "not_detected",
            "details": f"{command_name} not found",
        }

    status = cli_status(label, list_command)
    status["detected"] = True
    if status["connected"]:
        status["health"] = "connected"
    elif status["details"]:
        status["health"] = "not_configured"
    else:
        status["health"] = "unknown"
    return status


def local_server_doctor() -> dict[str, Any]:
    python = BASE_DIR / ".venv" / "Scripts" / "python.exe"
    smoke = BASE_DIR / "scripts" / "mcp-smoke-test.py"
    if not python.exists():
        return {
            "ok": False,
            "health": "venv_missing",
            "details": f"Python venv missing: {python}",
        }
    result = subprocess.run(
        [str(python), str(smoke)],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    output = normalize_display_text((result.stdout or "") + ("\n" + result.stderr if result.stderr else ""))
    return {
        "ok": result.returncode == 0,
        "health": "ok" if result.returncode == 0 else "failed",
        "details": output,
    }


def connect_codex() -> dict[str, Any]:
    remove_cmd = f"& codex.ps1 mcp remove {SERVER_NAME}"
    add_cmd = (
        f"& codex.ps1 mcp add {SERVER_NAME} -- "
        f"{quote_ps(resolve_pwsh_command())} '-NoLogo' '-NoProfile' '-File' {quote_ps(str(RUN_MCP))}"
    )
    return remove_then_add("codex", remove_cmd, add_cmd)


def connect_claude_code() -> dict[str, Any]:
    remove_cmd = f"& claude mcp remove -s user {SERVER_NAME}"
    add_cmd = (
        f"& claude mcp add -s user {SERVER_NAME} -- "
        f"{quote_ps(resolve_pwsh_command())} '-NoLogo' '-NoProfile' '-File' {quote_ps(str(RUN_MCP))}"
    )
    return remove_then_add("claude-code", remove_cmd, add_cmd)


def connect_gemini_cli() -> dict[str, Any]:
    remove_cmd = f"& gemini.ps1 mcp remove {SERVER_NAME}"
    add_cmd = (
        f"& gemini.ps1 mcp add -s user {SERVER_NAME} "
        f"{quote_ps(resolve_pwsh_command())} '-NoLogo' '-NoProfile' '-File' {quote_ps(str(RUN_MCP))}"
    )
    return remove_then_add("gemini-cli", remove_cmd, add_cmd)


def connect_qwen_cli() -> dict[str, Any]:
    remove_cmd = f"& qwen.ps1 mcp remove {SERVER_NAME}"
    add_cmd = (
        f"& qwen.ps1 mcp add -s user {SERVER_NAME} "
        f"{quote_ps(resolve_pwsh_command())} '-NoLogo' '-NoProfile' '-File' {quote_ps(str(RUN_MCP))}"
    )
    return remove_then_add("qwen-cli", remove_cmd, add_cmd)


def connect_cursor(backup_dir: Path) -> dict[str, Any]:
    result = merge_server_json(CURSOR_MCP, "mcpServers", SERVER_NAME, stdio_server_config(), backup_dir)
    result["target"] = "cursor"
    return result


def connect_claude_desktop(backup_dir: Path) -> dict[str, Any]:
    result = merge_server_json(CLAUDE_DESKTOP_CONFIG, "mcpServers", SERVER_NAME, stdio_server_config(), backup_dir)
    result["target"] = "claude-desktop"
    return result


def connect_vscode_copilot(backup_dir: Path) -> dict[str, Any]:
    result = merge_server_json(VSCODE_MCP, "servers", SERVER_NAME, stdio_server_config(), backup_dir)
    result["target"] = "copilot-vscode"
    return result


def connect_roo_code(backup_dir: Path) -> dict[str, Any]:
    if not ROO_MCP.parent.exists():
        return {"target": "roo-code", "status": "skipped", "reason": "not detected"}
    result = merge_server_json(ROO_MCP, "mcpServers", SERVER_NAME, stdio_server_config(), backup_dir)
    result["target"] = "roo-code"
    return result


def connect_kilocode(backup_dir: Path) -> dict[str, Any]:
    if not KILO_MCP.parent.exists():
        return {"target": "kilocode", "status": "skipped", "reason": "not detected"}
    result = merge_server_json(KILO_MCP, "mcpServers", SERVER_NAME, stdio_server_config(), backup_dir)
    result["target"] = "kilocode"
    return result


def connect_cline(backup_dir: Path) -> dict[str, Any]:
    if CLINE_VSCODE_MCP.exists():
        result = merge_server_json(CLINE_VSCODE_MCP, "mcpServers", SERVER_NAME, stdio_server_config(), backup_dir)
        result["target"] = "cline"
        return result
    if CLINE_CURSOR_MCP.exists():
        result = merge_server_json(CLINE_CURSOR_MCP, "mcpServers", SERVER_NAME, stdio_server_config(), backup_dir)
        result["target"] = "cline"
        return result
    return {"target": "cline", "status": "skipped", "reason": "not detected"}


def disconnect_codex() -> dict[str, Any]:
    return remove_only("codex", f"& codex.ps1 mcp remove {SERVER_NAME}")


def disconnect_claude_code() -> dict[str, Any]:
    return remove_only("claude-code", f"& claude mcp remove -s user {SERVER_NAME}")


def disconnect_gemini_cli() -> dict[str, Any]:
    return remove_only("gemini-cli", f"& gemini.ps1 mcp remove -s user {SERVER_NAME}")


def disconnect_qwen_cli() -> dict[str, Any]:
    return remove_only("qwen-cli", f"& qwen.ps1 mcp remove {SERVER_NAME}")


def disconnect_cursor(backup_dir: Path) -> dict[str, Any]:
    result = remove_server_json(CURSOR_MCP, "mcpServers", SERVER_NAME, backup_dir)
    result["target"] = "cursor"
    return result


def disconnect_claude_desktop(backup_dir: Path) -> dict[str, Any]:
    result = remove_server_json(CLAUDE_DESKTOP_CONFIG, "mcpServers", SERVER_NAME, backup_dir)
    result["target"] = "claude-desktop"
    return result


def disconnect_vscode_copilot(backup_dir: Path) -> dict[str, Any]:
    result = remove_server_json(VSCODE_MCP, "servers", SERVER_NAME, backup_dir)
    result["target"] = "copilot-vscode"
    return result


def disconnect_roo_code(backup_dir: Path) -> dict[str, Any]:
    if not ROO_MCP.parent.exists():
        return {"target": "roo-code", "status": "skipped", "reason": "not detected"}
    result = remove_server_json(ROO_MCP, "mcpServers", SERVER_NAME, backup_dir)
    result["target"] = "roo-code"
    return result


def disconnect_kilocode(backup_dir: Path) -> dict[str, Any]:
    if not KILO_MCP.parent.exists():
        return {"target": "kilocode", "status": "skipped", "reason": "not detected"}
    result = remove_server_json(KILO_MCP, "mcpServers", SERVER_NAME, backup_dir)
    result["target"] = "kilocode"
    return result


def disconnect_cline(backup_dir: Path) -> dict[str, Any]:
    if CLINE_VSCODE_MCP.exists():
        result = remove_server_json(CLINE_VSCODE_MCP, "mcpServers", SERVER_NAME, backup_dir)
        result["target"] = "cline"
        return result
    if CLINE_CURSOR_MCP.exists():
        result = remove_server_json(CLINE_CURSOR_MCP, "mcpServers", SERVER_NAME, backup_dir)
        result["target"] = "cline"
        return result
    return {"target": "cline", "status": "skipped", "reason": "not detected"}


def connect_all() -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUP_ROOT / timestamp
    results = [
        connect_codex(),
        connect_claude_code(),
        connect_claude_desktop(backup_dir),
        connect_gemini_cli(),
        connect_qwen_cli(),
        connect_cursor(backup_dir),
        connect_vscode_copilot(backup_dir),
        connect_roo_code(backup_dir),
        connect_kilocode(backup_dir),
        connect_cline(backup_dir),
    ]
    return {
        "server_name": SERVER_NAME,
        "server_command": stdio_server_config(),
        "backup_dir": str(backup_dir),
        "results": results,
    }


def disconnect_all() -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUP_ROOT / timestamp
    results = [
        disconnect_codex(),
        disconnect_claude_code(),
        disconnect_claude_desktop(backup_dir),
        disconnect_gemini_cli(),
        disconnect_qwen_cli(),
        disconnect_cursor(backup_dir),
        disconnect_vscode_copilot(backup_dir),
        disconnect_roo_code(backup_dir),
        disconnect_kilocode(backup_dir),
        disconnect_cline(backup_dir),
    ]
    return {
        "server_name": SERVER_NAME,
        "backup_dir": str(backup_dir),
        "results": results,
    }


def status_all() -> dict[str, Any]:
    results = [
        cli_status("codex", "& codex.ps1 mcp list"),
        cli_status("claude-code", "& claude mcp list"),
        config_status(CLAUDE_DESKTOP_CONFIG, "mcpServers", "claude-desktop"),
        cli_status("gemini-cli", "& gemini.ps1 mcp list"),
        cli_status("qwen-cli", "& qwen.ps1 mcp list"),
        config_status(CURSOR_MCP, "mcpServers", "cursor"),
        config_status(VSCODE_MCP, "servers", "copilot-vscode"),
        config_status(ROO_MCP, "mcpServers", "roo-code"),
        config_status(KILO_MCP, "mcpServers", "kilocode"),
        config_status(CLINE_VSCODE_MCP, "mcpServers", "cline"),
    ]
    if not CLINE_VSCODE_MCP.exists() and CLINE_CURSOR_MCP.exists():
        results[-1] = config_status(CLINE_CURSOR_MCP, "mcpServers", "cline")
    return {
        "server_name": SERVER_NAME,
        "results": results,
    }


def console_status_all() -> dict[str, Any]:
    results = [
        text_config_status(CODEX_CONFIG, "codex"),
        text_config_status(CLAUDE_CODE_CONFIG, "claude-code"),
        config_status(CLAUDE_DESKTOP_CONFIG, "mcpServers", "claude-desktop"),
        text_config_status(GEMINI_SETTINGS, "gemini-cli"),
        text_config_status(QWEN_SETTINGS, "qwen-cli"),
        config_status(CURSOR_MCP, "mcpServers", "cursor"),
        config_status(VSCODE_MCP, "servers", "copilot-vscode"),
        config_status(ROO_MCP, "mcpServers", "roo-code"),
        config_status(KILO_MCP, "mcpServers", "kilocode"),
        config_status(CLINE_VSCODE_MCP, "mcpServers", "cline"),
    ]
    if not CLINE_VSCODE_MCP.exists() and CLINE_CURSOR_MCP.exists():
        results[-1] = config_status(CLINE_CURSOR_MCP, "mcpServers", "cline")
    return {
        "server_name": SERVER_NAME,
        "results": results,
    }


def doctor_all() -> dict[str, Any]:
    results = [
        cli_doctor("codex", "codex.ps1", "& codex.ps1 mcp list"),
        cli_doctor("claude-code", "claude", "& claude mcp list"),
        config_doctor(CLAUDE_DESKTOP_CONFIG, "mcpServers", "claude-desktop"),
        cli_doctor("gemini-cli", "gemini.ps1", "& gemini.ps1 mcp list"),
        cli_doctor("qwen-cli", "qwen.ps1", "& qwen.ps1 mcp list"),
        config_doctor(CURSOR_MCP, "mcpServers", "cursor"),
        config_doctor(VSCODE_MCP, "servers", "copilot-vscode"),
        config_doctor(ROO_MCP, "mcpServers", "roo-code"),
        config_doctor(KILO_MCP, "mcpServers", "kilocode"),
        config_doctor(CLINE_VSCODE_MCP, "mcpServers", "cline"),
    ]
    if not CLINE_VSCODE_MCP.exists() and CLINE_CURSOR_MCP.exists():
        results[-1] = config_doctor(CLINE_CURSOR_MCP, "mcpServers", "cline")
    return {
        "server_name": SERVER_NAME,
        "local_server": local_server_doctor(),
        "results": results,
    }


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "connect"
    if command == "connect":
        payload = connect_all()
    elif command == "disconnect":
        payload = disconnect_all()
    elif command == "status":
        payload = status_all()
    elif command == "doctor":
        payload = doctor_all()
    else:
        print(json.dumps({"error": f"Unknown command: {command}"}, ensure_ascii=True, indent=2))
        return 1

    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
