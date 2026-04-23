"""Memory lifecycle utilities: TTL expiry and (opt-in) dedup on add.

TTL stores an `expires_at` ISO timestamp in the record's metadata. The
value is either provided directly by the caller or computed from a
`ttl_seconds` field at add time. Read paths filter expired records; a
background sweeper in api.main() hard-deletes them so the vector store
doesn't grow unboundedly.

Everything here is pure — no imports from runtime.operations or providers
— so it can be composed without circular-import headaches.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable


EXPIRES_AT_KEY = "expires_at"
TTL_SECONDS_KEY = "ttl_seconds"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_expires_at(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        stripped = value.strip()
        # Accept the canonical "...Z" suffix as well as explicit offsets.
        if stripped.endswith("Z"):
            stripped = stripped[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(stripped)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def resolve_expires_at(metadata: dict[str, Any] | None) -> str | None:
    """Compute the stored ISO expires_at from the caller's metadata.

    - If metadata.expires_at is present, it's normalized to a UTC ISO string.
    - If metadata.ttl_seconds is present and positive, expires_at is derived.
    - Explicit expires_at wins over ttl_seconds if both are given.
    """
    if not isinstance(metadata, dict):
        return None
    direct = _parse_expires_at(metadata.get(EXPIRES_AT_KEY))
    if direct is not None:
        return direct.isoformat()
    ttl = metadata.get(TTL_SECONDS_KEY)
    if isinstance(ttl, (int, float)) and ttl > 0:
        return (utc_now() + timedelta(seconds=float(ttl))).isoformat()
    return None


def apply_expiry_to_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a metadata dict with expires_at normalized and ttl_seconds dropped.

    This is the canonical shape we persist: downstream readers only have to
    check metadata.expires_at, they don't need to know about ttl_seconds.
    """
    if not isinstance(metadata, dict):
        return metadata
    expires_iso = resolve_expires_at(metadata)
    if expires_iso is None:
        # Caller passed nothing expiry-related, or ttl_seconds was non-positive.
        # Pass the original metadata through untouched except for dropping the
        # temporary ttl_seconds key if present.
        if TTL_SECONDS_KEY in metadata:
            cleaned = {k: v for k, v in metadata.items() if k != TTL_SECONDS_KEY}
            return cleaned
        return metadata
    cleaned = {k: v for k, v in metadata.items() if k != TTL_SECONDS_KEY}
    cleaned[EXPIRES_AT_KEY] = expires_iso
    return cleaned


def is_expired(record: dict[str, Any], *, now: datetime | None = None) -> bool:
    if not isinstance(record, dict):
        return False
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return False
    expires_dt = _parse_expires_at(metadata.get(EXPIRES_AT_KEY))
    if expires_dt is None:
        return False
    return expires_dt <= (now or utc_now())


def filter_unexpired(records: Iterable[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    snapshot_now = now or utc_now()
    return [r for r in records if not is_expired(r, now=snapshot_now)]


# ---------------------------------------------------------------------------
# Background sweeper
# ---------------------------------------------------------------------------

_SWEEP_INTERVAL_SECONDS_DEFAULT = 600  # 10 minutes
_SWEEP_ENV = "AGENTMEMORY_TTL_SWEEP_MINUTES"


def sweep_interval_seconds() -> int:
    raw = os.environ.get(_SWEEP_ENV, "").strip()
    if not raw:
        return _SWEEP_INTERVAL_SECONDS_DEFAULT
    try:
        minutes = float(raw)
    except ValueError:
        return _SWEEP_INTERVAL_SECONDS_DEFAULT
    if minutes <= 0:
        return 0  # disabled
    return int(minutes * 60)


def _collect_expired_ids(
    *,
    list_scopes: Callable[..., dict[str, Any]],
    list_memories: Callable[..., Any],
    list_expired_memory_ids: Callable[..., list[str]] | None = None,
) -> list[str]:
    """Walk the scope inventory and return ids of expired memories.

    Prefer the registry-backed TTL index when available. The legacy
    list_scopes + list_memories walk remains as a compatibility fallback.
    """
    if list_expired_memory_ids is not None:
        try:
            return _unique_ids(list_expired_memory_ids())
        except Exception:
            return []

    expired_ids: list[str] = []
    now = utc_now()
    try:
        inventory = list_scopes(limit=500)
    except Exception:
        return expired_ids
    scopes = inventory.get("items") if isinstance(inventory, dict) else None
    if not isinstance(scopes, list):
        return expired_ids
    for scope in scopes:
        kind = scope.get("kind")
        value = scope.get("value")
        if not isinstance(kind, str) or not isinstance(value, str) or not value:
            continue
        kwargs = {f"{kind}_id": value, "limit": 500}
        try:
            records = list_memories(**kwargs)
        except Exception:
            continue
        if not isinstance(records, list):
            continue
        for record in records:
            if is_expired(record, now=now):
                record_id = record.get("id")
                if isinstance(record_id, str):
                    expired_ids.append(record_id)
    return _unique_ids(expired_ids)


def _unique_ids(record_ids: Iterable[str]) -> list[str]:
    # De-dupe preserving order. The same record can appear under multiple
    # scopes (e.g. both user_id and agent_id), and registry rebuilds may
    # preserve provider duplicates defensively.
    seen: set[str] = set()
    unique_ids = []
    for record_id in record_ids:
        if isinstance(record_id, str) and record_id not in seen:
            seen.add(record_id)
            unique_ids.append(record_id)
    return unique_ids


def run_sweep_once(
    *,
    list_scopes: Callable[..., dict[str, Any]],
    list_memories: Callable[..., Any],
    delete_memory: Callable[..., Any],
    list_expired_memory_ids: Callable[..., list[str]] | None = None,
) -> dict[str, Any]:
    """Delete every expired memory once. Returns a summary for logs / metrics."""
    ids = _collect_expired_ids(
        list_scopes=list_scopes,
        list_memories=list_memories,
        list_expired_memory_ids=list_expired_memory_ids,
    )
    deleted = 0
    errors = 0
    for memory_id in ids:
        try:
            delete_memory(memory_id=memory_id)
            deleted += 1
        except Exception:
            errors += 1
    return {"swept": len(ids), "deleted": deleted, "errors": errors}


def start_sweeper_thread(
    *,
    list_scopes: Callable[..., dict[str, Any]],
    list_memories: Callable[..., Any],
    delete_memory: Callable[..., Any],
    list_expired_memory_ids: Callable[..., list[str]] | None = None,
    interval_seconds: int | None = None,
) -> threading.Thread | None:
    interval = sweep_interval_seconds() if interval_seconds is None else interval_seconds
    if interval <= 0:
        return None

    stop_event = threading.Event()

    def loop():
        # Warm up — don't sweep immediately on boot, wait one interval.
        while not stop_event.wait(interval):
            try:
                run_sweep_once(
                    list_scopes=list_scopes,
                    list_memories=list_memories,
                    delete_memory=delete_memory,
                    list_expired_memory_ids=list_expired_memory_ids,
                )
            except Exception:
                pass

    thread = threading.Thread(target=loop, name="agentmemory-ttl-sweeper", daemon=True)
    thread._agentmemory_stop_event = stop_event  # type: ignore[attr-defined]
    thread.start()
    return thread
