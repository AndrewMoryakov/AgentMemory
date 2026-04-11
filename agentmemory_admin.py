from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import agentmemory_clients
from agentmemory_runtime import (
    active_provider_name,
    memory_delete,
    memory_get,
    memory_list,
    memory_search,
    memory_update,
    runtime_info,
)
from memory_provider import (
    ProviderConfigurationError,
    ProviderScopeRequiredError,
    ProviderUnavailableError,
)


_STATE_LOCK = Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def admin_state_path() -> Path:
    return Path(runtime_info()["runtime_dir"]) / "admin-state.json"


def _read_state() -> dict[str, Any]:
    path = admin_state_path()
    if not path.exists():
        return {"records": {}, "updated_at": None}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(payload: dict[str, Any]) -> None:
    path = admin_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = utc_now()
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _memory_id(record: dict[str, Any]) -> str:
    memory_id = record.get("id") or record.get("memory_id")
    if not memory_id:
        raise KeyError("Memory record does not contain id or memory_id")
    return str(memory_id)


def _unwrap_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
        if "id" in payload or "memory_id" in payload:
            return [payload]
    return []


def _record_key(memory_id: str) -> str:
    return f"{active_provider_name()}:{memory_id}"


def _admin_overlay(memory_id: str) -> dict[str, Any]:
    with _STATE_LOCK:
        state = _read_state()
    return dict(state.get("records", {}).get(_record_key(memory_id), {}))


def _write_overlay(memory_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    with _STATE_LOCK:
        state = _read_state()
        records = state.setdefault("records", {})
        key = _record_key(memory_id)
        current = dict(records.get(key, {}))
        current.update(updates)
        current["updated_at"] = utc_now()
        records[key] = current
        _write_state(state)
        return dict(current)


def _remove_overlay(memory_id: str) -> None:
    with _STATE_LOCK:
        state = _read_state()
        records = state.setdefault("records", {})
        records.pop(_record_key(memory_id), None)
        _write_state(state)


def _normalize_memory_record(record: dict[str, Any]) -> dict[str, Any]:
    memory_id = _memory_id(record)
    overlay = _admin_overlay(memory_id)
    normalized = dict(record)
    normalized["id"] = memory_id
    normalized["provider"] = active_provider_name()
    normalized["pinned"] = bool(overlay.get("pinned", False))
    normalized["archived"] = bool(overlay.get("archived", False))
    normalized["admin_updated_at"] = overlay.get("updated_at")
    normalized["display_text"] = str(normalized.get("memory") or "")
    return normalized


def _matches_admin_filters(record: dict[str, Any], *, pinned: bool | None = None, archived: bool | None = None) -> bool:
    if pinned is not None and bool(record.get("pinned")) != pinned:
        return False
    if archived is not None and bool(record.get("archived")) != archived:
        return False
    return True


def admin_stats(*, limit: int = 500) -> dict[str, Any]:
    warning = None
    try:
        memories = list_admin_memories(limit=limit, include_archived=True)
    except Exception as exc:
        memories = []
        warning = f"memory listing unavailable: {exc}"
    try:
        client_status = agentmemory_clients.console_status_all()
    except Exception as exc:
        client_status = {
            "server_name": "agentmemory",
            "results": [],
            "warning": f"client status unavailable: {exc}",
        }
    connected_clients = sum(1 for item in client_status.get("results", []) if item.get("health") == "connected")
    configured_clients = sum(1 for item in client_status.get("results", []) if item.get("health") == "configured")
    stale_clients = sum(1 for item in client_status.get("results", []) if item.get("health") == "stale_config")
    return {
        "provider": active_provider_name(),
        "runtime": runtime_info(),
        "totals": {
            "memories": len(memories),
            "pinned": sum(1 for item in memories if item.get("pinned")),
            "archived": sum(1 for item in memories if item.get("archived")),
            "connected_clients": connected_clients,
            "configured_clients": configured_clients,
            "stale_clients": stale_clients,
        },
        "recent": memories[:10],
        "clients": client_status,
        "warning": warning,
    }


def list_admin_memories(
    *,
    query: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
    pinned: bool | None = None,
    archived: bool | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    try:
        if query:
            raw_records = memory_search(query=query, user_id=user_id, agent_id=agent_id, run_id=run_id, limit=limit)
        else:
            raw_records = memory_list(user_id=user_id, agent_id=agent_id, run_id=run_id, limit=limit)
    except (ProviderConfigurationError, ProviderScopeRequiredError, ProviderUnavailableError) as exc:
        message = str(exc)
        if "At least one of 'user_id', 'agent_id', or 'run_id' must be provided." in message:
            return []
        if "already accessed by another instance of Qdrant client" in message:
            return []
        raise
    except Exception as exc:
        raise ProviderUnavailableError(str(exc)) from exc
    records = _unwrap_records(raw_records)
    normalized = [_normalize_memory_record(record) for record in records]
    if archived is None and not include_archived:
        archived = False
    filtered = [item for item in normalized if _matches_admin_filters(item, pinned=pinned, archived=archived)]
    return filtered


def get_admin_memory(memory_id: str) -> dict[str, Any]:
    payload = memory_get(memory_id)
    records = _unwrap_records(payload)
    if records:
        return _normalize_memory_record(records[0])
    if isinstance(payload, dict):
        return _normalize_memory_record(payload)
    raise KeyError(memory_id)


def update_admin_memory(
    memory_id: str,
    *,
    memory: str | None = None,
    metadata: dict[str, Any] | None = None,
    pinned: bool | None = None,
    archived: bool | None = None,
) -> dict[str, Any]:
    if memory is not None or metadata is not None:
        current = memory_get(memory_id)
        next_memory = memory if memory is not None else current.get("memory") or ""
        next_metadata = metadata if metadata is not None else current.get("metadata")
        memory_update(memory_id=memory_id, data=next_memory, metadata=next_metadata)
    overlay_updates: dict[str, Any] = {}
    if pinned is not None:
        overlay_updates["pinned"] = bool(pinned)
    if archived is not None:
        overlay_updates["archived"] = bool(archived)
    if overlay_updates:
        _write_overlay(memory_id, overlay_updates)
    return get_admin_memory(memory_id)


def pin_admin_memory(memory_id: str, *, pinned: bool = True) -> dict[str, Any]:
    _write_overlay(memory_id, {"pinned": bool(pinned)})
    return get_admin_memory(memory_id)


def delete_admin_memory(memory_id: str) -> dict[str, Any]:
    result = memory_delete(memory_id=memory_id)
    _remove_overlay(memory_id)
    return result
