from __future__ import annotations

import contextlib
import base64
from datetime import datetime, timezone
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from agentmemory.providers.base import MemoryRecord, ProviderValidationError, ScopeInventory, ScopeInventoryItem, ScopeInventoryPage
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
    expires_at TEXT,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (provider, memory_id)
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_scope_registry_provider_user ON scope_registry(provider, user_id)",
    "CREATE INDEX IF NOT EXISTS idx_scope_registry_provider_agent ON scope_registry(provider, agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_scope_registry_provider_run ON scope_registry(provider, run_id)",
    "CREATE INDEX IF NOT EXISTS idx_scope_registry_provider_expires ON scope_registry(provider, expires_at)",
)


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
    for statement in _INDEXES:
        connection.execute(statement)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(scope_registry)").fetchall()}
    if "expires_at" not in columns:
        connection.execute("ALTER TABLE scope_registry ADD COLUMN expires_at TEXT")
        connection.commit()
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


def _metadata_expires_at(record: MemoryRecord) -> str | None:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return None
    expires_at = metadata.get("expires_at")
    return expires_at if isinstance(expires_at, str) and expires_at.strip() else None


def _parse_expires_at(value: str) -> datetime | None:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.endswith("Z"):
        stripped = stripped[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(stripped)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalized_row(provider_name: str, record: MemoryRecord) -> tuple[str, str, str | None, str | None, str | None, str | None, str | None, str | None]:
    return (
        provider_name,
        _memory_id(record),
        _scope_value(record, "user_id"),
        _scope_value(record, "agent_id"),
        _scope_value(record, "run_id"),
        _metadata_expires_at(record),
        record.get("created_at") if isinstance(record.get("created_at"), str) else None,
        record.get("updated_at") if isinstance(record.get("updated_at"), str) else None,
    )


def upsert_record(provider_name: str, record: MemoryRecord, runtime_dir: str) -> None:
    row = _normalized_row(provider_name, record)
    with _connect(runtime_dir) as connection:
        connection.execute(
            """
            INSERT INTO scope_registry (
                provider, memory_id, user_id, agent_id, run_id, expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, memory_id) DO UPDATE SET
                user_id = excluded.user_id,
                agent_id = excluded.agent_id,
                run_id = excluded.run_id,
                expires_at = excluded.expires_at,
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
                    provider, memory_id, user_id, agent_id, run_id, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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


def list_expired_memory_ids(provider_name: str, runtime_dir: str, *, now: datetime | None = None) -> list[str]:
    snapshot_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with _connect(runtime_dir) as connection:
        rows = connection.execute(
            """
            SELECT memory_id, expires_at
            FROM scope_registry
            WHERE provider = ? AND expires_at IS NOT NULL AND expires_at != ''
            """,
            (provider_name,),
        ).fetchall()
    expired_ids: list[str] = []
    for memory_id, expires_at in rows:
        if not isinstance(memory_id, str) or not isinstance(expires_at, str):
            continue
        expires_dt = _parse_expires_at(expires_at)
        if expires_dt is not None and expires_dt <= snapshot_now:
            expired_ids.append(memory_id)
    return expired_ids


def _scope_kind_field(kind: str) -> str:
    field_map = {"user": "user_id", "agent": "agent_id", "run": "run_id"}
    try:
        return field_map[kind]
    except KeyError as exc:
        raise ProviderValidationError("Scope kind must be one of: user, agent, run.") from exc


def _encode_cursor(offset: int) -> str:
    payload = json.dumps({"offset": offset}, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        offset = int(payload["offset"])
    except Exception as exc:
        raise ProviderValidationError("Invalid scope inventory cursor.") from exc
    if offset < 0:
        raise ProviderValidationError("Invalid scope inventory cursor.")
    return offset


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


def _inventory_items_and_totals(
    provider_name: str,
    kind: str | None,
    query: str | None,
    runtime_dir: str,
) -> tuple[list[ScopeInventoryItem], dict[str, int]]:
    if kind is not None:
        _scope_kind_field(kind)
    params: list[Any] = []
    query_clause = ""
    if isinstance(query, str) and query:
        query_clause = " AND lower({field}) LIKE ?"
        params.append(f"%{query.lower()}%")

    inventory_sql_parts: list[str] = []
    inventory_params: list[Any] = []
    for selected_kind, field_name in (("user", "user_id"), ("agent", "agent_id"), ("run", "run_id")):
        clause = query_clause.format(field=field_name) if query_clause else ""
        inventory_sql_parts.append(
            f"""
            SELECT
                '{selected_kind}' AS kind,
                {field_name} AS value,
                COUNT(*) AS count,
                MAX(COALESCE(updated_at, created_at)) AS last_seen_at
            FROM scope_registry
            WHERE provider = ?
              AND {field_name} IS NOT NULL
              AND TRIM({field_name}) != ''
              {clause}
            GROUP BY {field_name}
            """
        )
        inventory_params.append(provider_name)
        inventory_params.extend(params)

    inventory_sql = " UNION ALL ".join(inventory_sql_parts)
    filter_sql = " WHERE kind = ?" if kind is not None else ""
    filter_params: list[Any] = [kind] if kind is not None else []

    with _connect(runtime_dir) as connection:
        item_rows = connection.execute(
            f"""
            WITH inventory AS (
                {inventory_sql}
            )
            SELECT kind, value, count, last_seen_at
            FROM inventory
            {filter_sql}
            ORDER BY kind ASC, count DESC, value ASC
            """,
            inventory_params + filter_params,
        ).fetchall()
        totals_row = connection.execute(
            f"""
            WITH inventory AS (
                {inventory_sql}
            )
            SELECT
                SUM(CASE WHEN kind = 'user' THEN 1 ELSE 0 END) AS users,
                SUM(CASE WHEN kind = 'agent' THEN 1 ELSE 0 END) AS agents,
                SUM(CASE WHEN kind = 'run' THEN 1 ELSE 0 END) AS runs
            FROM inventory
            """,
            inventory_params,
        ).fetchone()

    items: list[ScopeInventoryItem] = [
        {
            "kind": row[0],
            "value": row[1],
            "count": row[2],
            "last_seen_at": row[3],
        }
        for row in item_rows
        if isinstance(row[0], str) and isinstance(row[1], str) and isinstance(row[2], int)
    ]
    totals = {
        "users": int(totals_row[0] or 0) if totals_row else 0,
        "agents": int(totals_row[1] or 0) if totals_row else 0,
        "runs": int(totals_row[2] or 0) if totals_row else 0,
    }
    return items, totals


def list_inventory(provider_name: str, limit: int, kind: str | None, query: str | None, runtime_dir: str) -> ScopeInventory:
    items, totals = _inventory_items_and_totals(provider_name, kind, query, runtime_dir)
    return {"provider": provider_name, "items": items[:limit], "totals": totals}


def list_inventory_page(
    provider_name: str,
    *,
    limit: int,
    cursor: str | None,
    kind: str | None,
    query: str | None,
    runtime_dir: str,
) -> ScopeInventoryPage:
    if limit < 1:
        raise ProviderValidationError("Scope inventory page limit must be at least 1.")
    offset = _decode_cursor(cursor)
    if kind is not None:
        _scope_kind_field(kind)

    params: list[Any] = []
    query_clause = ""
    if isinstance(query, str) and query:
        query_clause = " AND lower({field}) LIKE ?"
        params.append(f"%{query.lower()}%")

    inventory_sql_parts: list[str] = []
    inventory_params: list[Any] = []
    for selected_kind, field_name in (("user", "user_id"), ("agent", "agent_id"), ("run", "run_id")):
        clause = query_clause.format(field=field_name) if query_clause else ""
        inventory_sql_parts.append(
            f"""
            SELECT
                '{selected_kind}' AS kind,
                {field_name} AS value,
                COUNT(*) AS count,
                MAX(COALESCE(updated_at, created_at)) AS last_seen_at
            FROM scope_registry
            WHERE provider = ?
              AND {field_name} IS NOT NULL
              AND TRIM({field_name}) != ''
              {clause}
            GROUP BY {field_name}
            """
        )
        inventory_params.append(provider_name)
        inventory_params.extend(params)
    inventory_sql = " UNION ALL ".join(inventory_sql_parts)
    filter_sql = " WHERE kind = ?" if kind is not None else ""
    filter_params: list[Any] = [kind] if kind is not None else []

    with _connect(runtime_dir) as connection:
        page_rows = connection.execute(
            f"""
            WITH inventory AS (
                {inventory_sql}
            )
            SELECT kind, value, count, last_seen_at
            FROM inventory
            {filter_sql}
            ORDER BY kind ASC, count DESC, value ASC
            LIMIT ? OFFSET ?
            """,
            inventory_params + filter_params + [limit + 1, offset],
        ).fetchall()
        totals_row = connection.execute(
            f"""
            WITH inventory AS (
                {inventory_sql}
            )
            SELECT
                SUM(CASE WHEN kind = 'user' THEN 1 ELSE 0 END) AS users,
                SUM(CASE WHEN kind = 'agent' THEN 1 ELSE 0 END) AS agents,
                SUM(CASE WHEN kind = 'run' THEN 1 ELSE 0 END) AS runs
            FROM inventory
            """,
            inventory_params,
        ).fetchone()
    has_more = len(page_rows) > limit
    materialized_rows = page_rows[:limit]
    page_items: list[ScopeInventoryItem] = [
        {
            "kind": row[0],
            "value": row[1],
            "count": row[2],
            "last_seen_at": row[3],
        }
        for row in materialized_rows
        if isinstance(row[0], str) and isinstance(row[1], str) and isinstance(row[2], int)
    ]
    next_offset = offset + len(page_items)
    next_cursor = _encode_cursor(next_offset) if has_more else None
    totals = {
        "users": int(totals_row[0] or 0) if totals_row else 0,
        "agents": int(totals_row[1] or 0) if totals_row else 0,
        "runs": int(totals_row[2] or 0) if totals_row else 0,
    }
    return {
        "provider": provider_name,
        "items": page_items,
        "totals": totals,
        "next_cursor": next_cursor,
        "pagination_supported": True,
    }
