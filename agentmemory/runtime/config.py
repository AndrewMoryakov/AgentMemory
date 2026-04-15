from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from agentmemory.providers.base import (
    BaseMemoryProvider,
    MemoryRecord,
    ProviderCapabilities,
    ProviderConfigurationError,
    ProviderContract,
    ProviderRuntimePolicy,
)


CONFIG_VERSION = 2
DEFAULT_PROFILE = "default"
PROFILE_ENV = "AGENTMEMORY_PROFILE"


def _looks_like_agentmemory_root(path: Path) -> bool:
    markers = [
        path / "pyproject.toml",
        path / "scripts" / "run-agentmemory-python.sh",
        path / "scripts" / "run-agentmemory-python.ps1",
        path / "web",
    ]
    return any(marker.exists() for marker in markers)


def discover_base_dir() -> Path:
    explicit = os.environ.get("AGENTMEMORY_HOME")
    if explicit:
        return Path(explicit).expanduser().resolve()

    cwd = Path.cwd().resolve()
    if _looks_like_agentmemory_root(cwd):
        return cwd

    for candidate in Path(__file__).resolve().parents:
        if _looks_like_agentmemory_root(candidate):
            return candidate

    return cwd


BASE_DIR = discover_base_dir()
CONFIG_PATH = BASE_DIR / "agentmemory.config.json"
ENV_PATH = BASE_DIR / ".env"
RUNTIME_DIR = BASE_DIR / "data"
API_PID_FILE = BASE_DIR / "data" / "agentmemory-api.pid"
API_STATE_FILE = BASE_DIR / "data" / "agentmemory-api.json"
PLACEHOLDER_KEYS = {"paste-your-openrouter-key-here", "YOUR_OPENROUTER_API_KEY"}


def load_dotenv(env_path: Path = ENV_PATH, *, override: bool = False) -> dict[str, str]:
    loaded: dict[str, str] = {}
    if not env_path.exists():
        return loaded

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = value
        loaded[key] = value
    return loaded


load_dotenv()


def provider_registry() -> dict[str, type[BaseMemoryProvider]]:
    from agentmemory.providers.localjson import LocalJsonProvider
    from agentmemory.providers.mem0 import Mem0Provider

    return {
        "localjson": LocalJsonProvider,
        "mem0": Mem0Provider,
    }


def provider_class(provider_name: str) -> type[BaseMemoryProvider]:
    registry = provider_registry()
    if provider_name not in registry:
        raise ProviderConfigurationError(f"Unknown memory provider: {provider_name}")
    return registry[provider_name]


def clone_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value))


def profile_runtime_dir(profile_name: str) -> str:
    runtime_path = RUNTIME_DIR if profile_name == DEFAULT_PROFILE else (RUNTIME_DIR / profile_name)
    return str(runtime_path)


def next_profile_api_port(document: dict[str, Any]) -> int:
    used_ports: set[int] = set()
    for profile in document.get("profiles", {}).values():
        runtime = profile.get("runtime", {})
        port = runtime.get("api_port")
        try:
            used_ports.add(int(port))
        except (TypeError, ValueError):
            continue
    candidate = 8765
    while candidate in used_ports:
        candidate += 1
    return candidate


def build_profile_config(profile_name: str, *, api_port: int | None = None, provider_name: str = "mem0") -> dict[str, Any]:
    registry = provider_registry()
    runtime_dir = profile_runtime_dir(profile_name)
    selected_port = api_port if api_port is not None else 8765
    return {
        "runtime": {
            "provider": provider_name,
            "runtime_dir": runtime_dir,
            "api_host": "127.0.0.1",
            "api_port": selected_port,
        },
        "providers": {
            provider_name: registry[provider_name].default_provider_config(runtime_dir=runtime_dir),
        },
    }


def default_runtime_config() -> dict[str, Any]:
    return build_profile_config(DEFAULT_PROFILE)


def default_runtime_document() -> dict[str, Any]:
    return {
        "config_version": CONFIG_VERSION,
        "active_profile": DEFAULT_PROFILE,
        "profiles": {
            DEFAULT_PROFILE: default_runtime_config(),
        },
    }


def normalize_runtime_document(raw: dict[str, Any]) -> dict[str, Any]:
    if "profiles" not in raw:
        return {
            "config_version": CONFIG_VERSION,
            "active_profile": DEFAULT_PROFILE,
            "profiles": {
                DEFAULT_PROFILE: clone_jsonable(raw),
            },
        }

    profiles = raw.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ProviderConfigurationError("Runtime config must include at least one profile.")
    active_profile = str(raw.get("active_profile") or DEFAULT_PROFILE)
    if active_profile not in profiles:
        active_profile = next(iter(profiles.keys()))
    return {
        "config_version": int(raw.get("config_version", CONFIG_VERSION)),
        "active_profile": active_profile,
        "profiles": clone_jsonable(profiles),
    }


def current_profile_name(*, document: dict[str, Any] | None = None) -> str:
    selected = os.environ.get(PROFILE_ENV)
    if selected:
        if document is not None and selected not in document.get("profiles", {}):
            raise ProviderConfigurationError(f"Unknown AgentMemory profile: {selected}")
        return selected
    if document is None:
        document = load_runtime_config_document()
    return str(document.get("active_profile") or DEFAULT_PROFILE)


def effective_config_from_document(document: dict[str, Any], *, profile_name: str | None = None) -> dict[str, Any]:
    selected_profile = profile_name or current_profile_name(document=document)
    profiles = document.get("profiles", {})
    if selected_profile not in profiles:
        raise ProviderConfigurationError(f"Unknown AgentMemory profile: {selected_profile}")
    return clone_jsonable(profiles[selected_profile])


def write_runtime_config_document(document: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(normalize_runtime_document(document), ensure_ascii=True, indent=2) + "\n", encoding="ascii")
    clear_caches()


def write_runtime_config(config: dict[str, Any]) -> None:
    if "profiles" in config:
        write_runtime_config_document(config)
        return

    if CONFIG_PATH.exists():
        document = load_runtime_config_document()
    else:
        document = default_runtime_document()
    profile_name = current_profile_name(document=document)
    document["profiles"][profile_name] = clone_jsonable(config)
    document["active_profile"] = profile_name
    write_runtime_config_document(document)


@lru_cache(maxsize=1)
def load_runtime_config_document_with_source() -> tuple[dict[str, Any], str, Path]:
    if CONFIG_PATH.exists():
        raw = json.loads(CONFIG_PATH.read_text(encoding="ascii"))
        return normalize_runtime_document(raw), "generic", CONFIG_PATH
    return default_runtime_document(), "default", CONFIG_PATH


def load_runtime_config_document() -> dict[str, Any]:
    return load_runtime_config_document_with_source()[0]


@lru_cache(maxsize=1)
def load_runtime_config_with_source() -> tuple[dict[str, Any], str, Path]:
    document, source, path = load_runtime_config_document_with_source()
    return effective_config_from_document(document), source, path


def load_runtime_config() -> dict[str, Any]:
    return load_runtime_config_with_source()[0]


def current_api_host() -> str:
    config = load_runtime_config()
    return os.environ.get("AGENTMEMORY_API_HOST", config["runtime"].get("api_host", "127.0.0.1"))


def current_api_port() -> int:
    config = load_runtime_config()
    return int(os.environ.get("AGENTMEMORY_API_PORT", str(config["runtime"].get("api_port", 8765))))


@lru_cache(maxsize=1)
def get_provider() -> BaseMemoryProvider:
    config, _source, _path = load_runtime_config_with_source()
    provider_name = config["runtime"]["provider"]
    provider_type = provider_class(provider_name)
    return provider_type(runtime_config=config["runtime"], provider_config=config["providers"][provider_name])


def clear_caches() -> None:
    load_runtime_config_document_with_source.cache_clear()
    load_runtime_config_with_source.cache_clear()
    get_provider.cache_clear()


def ensure_default_runtime_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        write_runtime_config_document(default_runtime_document())
    return load_runtime_config()


def write_env_values(values: dict[str, str]) -> None:
    current: dict[str, str] = {}
    if ENV_PATH.exists():
        current.update(load_dotenv(ENV_PATH, override=False))
    current.update({k: v for k, v in values.items() if v is not None})

    lines = [
        "# AgentMemory local environment",
        "# Generated by agentmemory",
    ]
    for key in sorted(current):
        lines.append(f"{key}={current[key]}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    load_dotenv(override=True)
    clear_caches()


def list_profile_names() -> list[str]:
    document = load_runtime_config_document()
    return sorted(document.get("profiles", {}).keys())


def create_profile(profile_name: str, *, copy_from: str | None = None) -> dict[str, Any]:
    document = load_runtime_config_document()
    if profile_name in document["profiles"]:
        raise ProviderConfigurationError(f"Profile '{profile_name}' already exists.")
    if copy_from:
        if copy_from not in document["profiles"]:
            raise ProviderConfigurationError(f"Source profile '{copy_from}' does not exist.")
        profile = clone_jsonable(document["profiles"][copy_from])
    else:
        profile = build_profile_config(profile_name, api_port=next_profile_api_port(document))
    document["profiles"][profile_name] = profile
    write_runtime_config_document(document)
    return clone_jsonable(profile)


def set_active_profile(profile_name: str) -> None:
    document = load_runtime_config_document()
    if profile_name not in document["profiles"]:
        raise ProviderConfigurationError(f"Profile '{profile_name}' does not exist.")
    document["active_profile"] = profile_name
    write_runtime_config_document(document)


def active_provider_name() -> str:
    config = load_runtime_config()
    return config["runtime"]["provider"]


def active_provider_capabilities() -> ProviderCapabilities:
    return get_provider().capabilities()


def active_provider_runtime_policy() -> ProviderRuntimePolicy:
    return get_provider().runtime_policy()


def active_provider_contract() -> ProviderContract:
    return get_provider().provider_contract()


def runtime_identity() -> dict[str, Any]:
    profile_name = current_profile_name()
    runtime_id = hashlib.sha256(f"{BASE_DIR.resolve()}::{profile_name}".encode("utf-8")).hexdigest()[:12]
    return {
        "config_version": CONFIG_VERSION,
        "profile": profile_name,
        "runtime_id": runtime_id,
        "owner_process": os.environ.get("AGENTMEMORY_OWNER_PROCESS") == "1",
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_api_pid() -> int | None:
    if not API_PID_FILE.exists():
        return None
    try:
        return int(API_PID_FILE.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def process_exists(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return str(pid) in proc.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def can_bind_api_port(host: str, port: int) -> bool:
    try:
        with socket.create_server((host, port), backlog=1):
            return True
    except OSError:
        return False


def listening_pid_for_api_port(host: str, port: int) -> int | None:
    if os.name == "nt":
        try:
            script = (
                "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
                f"Where-Object {{ $_.LocalPort -eq {port} -and ($_.LocalAddress -eq '{host}' -or $_.LocalAddress -eq '0.0.0.0' -or $_.LocalAddress -eq '::') }} | "
                "Select-Object -First 1 -ExpandProperty OwningProcess"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            value = result.stdout.strip()
            return int(value) if value else None
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    try:
        result = subprocess.run(
            ["sh", "-lc", f"lsof -nP -iTCP:{port} -sTCP:LISTEN -t 2>/dev/null | head -n 1"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        value = result.stdout.strip()
        return int(value) if value else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def api_health_payload(host: str, port: int, *, timeout_seconds: float = 2.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def read_api_state() -> dict[str, Any] | None:
    if not API_STATE_FILE.exists():
        return None
    try:
        payload = json.loads(API_STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except (OSError, ValueError):
        return None
    return None


def write_api_state(*, pid: int, host: str, port: int) -> None:
    API_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": pid,
        "host": host,
        "port": port,
        "started_at": utc_now(),
        "runtime_id": runtime_identity()["runtime_id"],
        "profile": current_profile_name(),
        "provider": active_provider_name(),
    }
    API_STATE_FILE.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="ascii")


def remove_api_state() -> None:
    API_STATE_FILE.unlink(missing_ok=True)


def api_runtime_diagnostics() -> dict[str, Any]:
    host = current_api_host()
    port = current_api_port()
    pid = read_api_pid()
    state = read_api_state()
    current_runtime_id = runtime_identity()["runtime_id"]

    if os.environ.get("AGENTMEMORY_OWNER_PROCESS") == "1":
        state_pid = state.get("pid") if isinstance(state, dict) else None
        state_runtime_id = state.get("runtime_id") if isinstance(state, dict) else None
        return {
            "status": "running",
            "expected_url": f"http://{host}:{port}",
            "pid_file": str(API_PID_FILE),
            "state_file": str(API_STATE_FILE),
            "recorded_pid": pid,
            "recorded_pid_running": process_exists(pid),
            "listener_pid": os.getpid(),
            "listener_healthy": True,
            "listener_runtime_id": current_runtime_id,
            "listener_runtime_matches_current": True,
            "recorded_pid_owns_listener": pid == os.getpid() if pid is not None else False,
            "recorded_state": state,
            "recorded_state_pid_matches": state_pid == pid if state is not None else None,
            "recorded_runtime_matches_current": state_runtime_id == current_runtime_id if state is not None else False,
            "port_available": False,
        }

    process_running = process_exists(pid)
    port_available = can_bind_api_port(host, port)
    listener_pid = listening_pid_for_api_port(host, port)
    recorded_pid_owns_listener = bool(pid and listener_pid and pid == listener_pid)
    state_runtime_id = state.get("runtime_id") if isinstance(state, dict) else None
    state_pid = state.get("pid") if isinstance(state, dict) else None
    matches_current_runtime = bool(state_runtime_id and state_runtime_id == current_runtime_id)
    probe_listener_health = os.environ.get("AGENTMEMORY_OWNER_PROCESS") != "1"
    listener_health = (
        api_health_payload(host, port, timeout_seconds=1.0)
        if listener_pid is not None and probe_listener_health
        else None
    )
    listener_runtime_id = None
    if isinstance(listener_health, dict):
        listener_runtime = listener_health.get("runtime_identity")
        if isinstance(listener_runtime, dict):
            listener_runtime_id = listener_runtime.get("runtime_id")
    listener_matches_current_runtime = bool(listener_runtime_id and listener_runtime_id == current_runtime_id)

    if process_running and recorded_pid_owns_listener and matches_current_runtime:
        status = "running"
    elif listener_matches_current_runtime and listener_pid is not None:
        status = "running_untracked"
    elif process_running and listener_pid is not None and not recorded_pid_owns_listener:
        status = "foreign_listener_conflict"
    elif process_running and port_available:
        status = "stale_process_record"
    elif not process_running and not port_available:
        status = "port_occupied"
    elif not process_running and state is not None:
        status = "stale_state"
    else:
        status = "available"

    return {
        "status": status,
        "expected_url": f"http://{host}:{port}",
        "pid_file": str(API_PID_FILE),
        "state_file": str(API_STATE_FILE),
        "recorded_pid": pid,
        "recorded_pid_running": process_running,
        "listener_pid": listener_pid,
        "listener_healthy": bool(listener_health and listener_health.get("ok") is True),
        "listener_runtime_id": listener_runtime_id,
        "listener_runtime_matches_current": listener_matches_current_runtime,
        "recorded_pid_owns_listener": recorded_pid_owns_listener,
        "recorded_state": state,
        "recorded_state_pid_matches": state_pid == pid if state is not None else None,
        "recorded_runtime_matches_current": matches_current_runtime,
        "port_available": port_available,
    }


def runtime_info() -> dict[str, Any]:
    config, source, config_path = load_runtime_config_with_source()
    provider = get_provider()
    runtime = config["runtime"]
    identity = runtime_identity()
    return {
        "base_dir": str(BASE_DIR),
        "config_path": str(config_path),
        "env_path": str(ENV_PATH),
        "runtime_dir": runtime.get("runtime_dir", str(RUNTIME_DIR)),
        "api_host": current_api_host(),
        "api_port": current_api_port(),
        "provider": active_provider_name(),
        "active_profile": identity["profile"],
        "profiles": list_profile_names(),
        "runtime_identity": identity,
        "api_runtime": api_runtime_diagnostics(),
        "capabilities": active_provider_capabilities(),
        "runtime_policy": active_provider_runtime_policy(),
        "provider_contract": active_provider_contract(),
        "config_source": source,
        **provider.runtime_info(),
    }


def health() -> dict[str, Any]:
    return {"ok": True, **runtime_info()}


def memory_add(*, messages, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None):
    return get_provider().add_memory(
        messages=messages,
        user_id=user_id,
        agent_id=agent_id,
        run_id=run_id,
        metadata=metadata,
        infer=infer,
        memory_type=memory_type,
    )


def memory_search(*, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True):
    return get_provider().search_memory(
        query=query,
        user_id=user_id,
        agent_id=agent_id,
        run_id=run_id,
        limit=limit,
        filters=filters,
        threshold=threshold,
        rerank=rerank,
    )


def memory_list(*, user_id=None, agent_id=None, run_id=None, limit=100, filters=None):
    return get_provider().list_memories(
        user_id=user_id,
        agent_id=agent_id,
        run_id=run_id,
        limit=limit,
        filters=filters,
    )


def memory_get(memory_id) -> MemoryRecord:
    return get_provider().get_memory(memory_id)


def memory_update(*, memory_id, data, metadata=None):
    return get_provider().update_memory(memory_id=memory_id, data=data, metadata=metadata)


def memory_delete(*, memory_id):
    return get_provider().delete_memory(memory_id=memory_id)


def memory_list_scopes(*, limit: int = 200, kind: str | None = None, query: str | None = None):
    return get_provider().list_scopes(limit=limit, kind=kind, query=query)
