from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from agentmemory.providers.base import MemoryRecord, ProviderValidationError, ScopeInventory, ScopeInventoryItem
from agentmemory.runtime.atomic_io import atomic_write_json

if os.name == "nt":
    import msvcrt
else:
    import fcntl


_SCHEMA = """
CREATE TABLE IF NOT EXISTS scope_registry (
    provider TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    user_id TEXT,
    agent_id TEXT,
    run_id TEXT,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (provider, memory_id)
)
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def registry_path(runtime_dir: str) -> Path:
    return Path(runtime_dir) / "scope-registry.sqlite3"


def status_path(runtime_dir: str) -> Path:
    return Path(runtime_dir) / "scope-registry-status.json"


def _default_status(provider_name: str) -> dict[str, Any]:
    return {
        "provider": provider_name,
        "status": "ok",
        "last_error": None,
        "last_error_at": None,
        "last_rebuild_at": None,
        "last_failed_operation": None,
        "memory_id": None,
    }


@contextlib.contextmanager
def _status_lock(runtime_dir: str) -> Iterator[None]:
    path = status_path(runtime_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0)
        if os.name == "nt":
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock_file.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_status_document(runtime_dir: str) -> dict[str, Any]:
    path = status_path(runtime_dir)
    if not path.exists():
        return {"providers": {}, "updated_at": None}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_status_document(runtime_dir: str, payload: dict[str, Any]) -> None:
    payload["updated_at"] = utc_now()
    atomic_write_json(status_path(runtime_dir), payload)


@contextlib.contextmanager
def _connect(runtime_dir: str) -> Iterator[sqlite3.Connection]:
    path = registry_path(runtime_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute(_SCHEMA)
    try:
        yield connection
    finally:
        connection.close()


def _memory_id(record: MemoryRecord) -> str:
    memory_id = record.get("id")
    if not isinstance(memory_id, str) or not memory_id.strip():
        raise ProviderValidationError("Scope registry record requires a non-empty id.")
    return memory_id


def _scope_value(record: MemoryRecord, field_name: str) -> str | None:
    value = record.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    stripped = value.strip()
    return stripped or None


def _normalized_row(provider_name: str, record: MemoryRecord) -> tuple[str, str, str | None, str | None, str | None, str | None, str | None]:
    return (
        provider_name,
        _memory_id(record),
        _scope_value(record, "user_id"),
        _scope_value(record, "agent_id"),
        _scope_value(record, "run_id"),
        record.get("created_at") if isinstance(record.get("created_at"), str) else None,
        record.get("updated_at") if isinstance(record.get("updated_at"), str) else None,
    )


def upsert_record(provider_name: str, record: MemoryRecord, runtime_dir: str) -> None:
    row = _normalized_row(provider_name, record)
    with _connect(runtime_dir) as connection:
        connection.execute(
            """
            INSERT INTO scope_registry (
                provider, memory_id, user_id, agent_id, run_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, memory_id) DO UPDATE SET
                user_id = excluded.user_id,
                agent_id = excluded.agent_id,
                run_id = excluded.run_id,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            row,
        )
        connection.commit()


def delete_record(provider_name: str, memory_id: str, runtime_dir: str) -> None:
    with _connect(runtime_dir) as connection:
        connection.execute(
            "DELETE FROM scope_registry WHERE provider = ? AND memory_id = ?",
            (provider_name, memory_id),
        )
        connection.commit()


def replace_provider_records(provider_name: str, records: list[MemoryRecord], runtime_dir: str) -> dict[str, int]:
    rows = [_normalized_row(provider_name, record) for record in records]
    with _connect(runtime_dir) as connection:
        connection.execute("DELETE FROM scope_registry WHERE provider = ?", (provider_name,))
        if rows:
            connection.executemany(
                """
                INSERT INTO scope_registry (
                    provider, memory_id, user_id, agent_id, run_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        connection.commit()
    return {
        "records": len(rows),
        "users": len({row[2] for row in rows if row[2]}),
        "agents": len({row[3] for row in rows if row[3]}),
        "runs": len({row[4] for row in rows if row[4]}),
    }


def _scope_kind_field(kind: str) -> str:
    field_map = {"user": "user_id", "agent": "agent_id", "run": "run_id"}
    try:
        return field_map[kind]
    except KeyError as exc:
        raise ProviderValidationError("Scope kind must be one of: user, agent, run.") from exc


def mark_sync_failed(
    provider_name: str,
    runtime_dir: str,
    *,
    operation: str,
    memory_id: str | None,
    error: Exception,
) -> None:
    with _status_lock(runtime_dir):
        payload = _read_status_document(runtime_dir)
        providers = payload.setdefault("providers", {})
        current = dict(providers.get(provider_name, _default_status(provider_name)))
        current.update(
            {
                "provider": provider_name,
                "status": "needs_rebuild",
                "last_error": f"{error.__class__.__name__}: {error}",
                "last_error_at": utc_now(),
                "last_failed_operation": operation,
                "memory_id": memory_id,
            }
        )
        providers[provider_name] = current
        _write_status_document(runtime_dir, payload)


def clear_sync_failure(provider_name: str, runtime_dir: str, *, rebuilt: bool = False) -> None:
    with _status_lock(runtime_dir):
        payload = _read_status_document(runtime_dir)
        providers = payload.setdefault("providers", {})
        current = dict(providers.get(provider_name, _default_status(provider_name)))
        current.update(
            {
                "provider": provider_name,
                "status": "ok",
                "last_error": None,
                "last_error_at": None,
                "last_failed_operation": None,
                "memory_id": None,
            }
        )
        if rebuilt:
            current["last_rebuild_at"] = utc_now()
        providers[provider_name] = current
        _write_status_document(runtime_dir, payload)


def scope_registry_status(provider_name: str, runtime_dir: str) -> dict[str, Any]:
    with _status_lock(runtime_dir):
        payload = _read_status_document(runtime_dir)
    current = dict(_default_status(provider_name))
    current.update(payload.get("providers", {}).get(provider_name, {}))
    current["provider"] = provider_name
    return current


def list_inventory(provider_name: str, limit: int, kind: str | None, query: str | None, runtime_dir: str) -> ScopeInventory:
    if kind is not None:
        _scope_kind_field(kind)

    query_l = query.lower() if isinstance(query, str) and query else None
    with _connect(runtime_dir) as connection:
        rows = connection.execute(
            """
            SELECT user_id, agent_id, run_id, created_at, updated_at
            FROM scope_registry
            WHERE provider = ?
            """,
            (provider_name,),
        ).fetchall()

    buckets: dict[tuple[str, str], ScopeInventoryItem] = {}
    field_map = {"user": 0, "agent": 1, "run": 2}

    for row in rows:
        created_at = row[3]
        updated_at = row[4]
        for selected_kind, index in field_map.items():
            value = row[index]
            if not isinstance(value, str) or not value.strip():
                continue
            if query_l and query_l not in value.lower():
                continue
            key = (selected_kind, value)
            item = buckets.setdefault(
                key,
                {"kind": selected_kind, "value": value, "count": 0, "last_seen_at": None},
            )
            item["count"] += 1
            timestamp = updated_at or created_at
            if isinstance(timestamp, str) and timestamp and (item["last_seen_at"] is None or timestamp > item["last_seen_at"]):
                item["last_seen_at"] = timestamp

    all_items = sorted(buckets.values(), key=lambda item: (item["kind"], -item["count"], item["value"]))
    items = [item for item in all_items if kind is None or item["kind"] == kind]
    totals = {
        "users": sum(1 for item in all_items if item["kind"] == "user"),
        "agents": sum(1 for item in all_items if item["kind"] == "agent"),
        "runs": sum(1 for item in all_items if item["kind"] == "run"),
    }
    return {"provider": provider_name, "items": items[:limit], "totals": totals}
