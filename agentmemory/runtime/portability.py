from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentmemory.providers.base import MemoryRecord, ProviderValidationError
from agentmemory.runtime.config import (
    active_provider_capabilities,
    active_provider_name,
    memory_add,
    memory_list,
    memory_list_scopes,
)


EXPORT_SCOPE_LIMIT = 10_000
EXPORT_RECORD_LIMIT = 10_000
EXPORTED_RECORD_KEYS = (
    "id",
    "memory",
    "metadata",
    "user_id",
    "agent_id",
    "run_id",
    "memory_type",
    "created_at",
    "updated_at",
    "provider",
)


def _canonical_export_record(record: MemoryRecord, *, provider_name: str) -> dict[str, Any]:
    canonical: dict[str, Any] = {}
    for key in EXPORTED_RECORD_KEYS:
        if key == "provider":
            canonical[key] = record.get(key) or provider_name
            continue
        if key in record:
            canonical[key] = record.get(key)
    if "metadata" not in canonical or canonical["metadata"] is None:
        canonical["metadata"] = {}
    if not isinstance(canonical["metadata"], dict):
        raise ProviderValidationError("Memory metadata must be a JSON object for export.")
    return canonical


def _record_identity(record: MemoryRecord) -> str:
    memory_id = record.get("id")
    if isinstance(memory_id, str) and memory_id:
        return memory_id
    memory_text = record.get("memory") if isinstance(record.get("memory"), str) else ""
    return json.dumps(
        {
            "memory": memory_text,
            "user_id": record.get("user_id"),
            "agent_id": record.get("agent_id"),
            "run_id": record.get("run_id"),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def _collect_export_records() -> tuple[str, list[dict[str, Any]], int, bool]:
    provider_name = active_provider_name()
    capabilities = active_provider_capabilities()
    inventory = memory_list_scopes(limit=EXPORT_SCOPE_LIMIT)
    items = inventory.get("items", [])
    if len(items) >= EXPORT_SCOPE_LIMIT:
        raise ProviderValidationError(
            "Export may be truncated because scope inventory reached the current export limit. "
            "This provider needs pagination support before larger exports are safe."
        )

    seen: dict[str, dict[str, Any]] = {}
    scoped_passes = 0
    for item in items:
        kind = item.get("kind")
        value = item.get("value")
        if kind not in {"user", "agent", "run"} or not isinstance(value, str) or not value:
            continue
        scoped_passes += 1
        records = memory_list(**{f"{kind}_id": value, "limit": EXPORT_RECORD_LIMIT})
        if len(records) >= EXPORT_RECORD_LIMIT:
            raise ProviderValidationError(
                f"Export may be truncated for {kind} '{value}' because the provider returned "
                f"{EXPORT_RECORD_LIMIT} records without pagination."
            )
        for record in records:
            seen.setdefault(
                _record_identity(record),
                _canonical_export_record(record, provider_name=provider_name),
            )

    included_scopeless = False
    if capabilities.get("supports_scopeless_list"):
        included_scopeless = True
        records = memory_list(limit=EXPORT_RECORD_LIMIT)
        if len(records) >= EXPORT_RECORD_LIMIT:
            raise ProviderValidationError(
                "Export may be truncated for scopeless list because the provider returned "
                f"{EXPORT_RECORD_LIMIT} records without pagination."
            )
        for record in records:
            seen.setdefault(
                _record_identity(record),
                _canonical_export_record(record, provider_name=provider_name),
            )

    ordered = sorted(
        seen.values(),
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("updated_at") or ""),
            str(item.get("id") or ""),
            str(item.get("memory") or ""),
        ),
    )
    return provider_name, ordered, scoped_passes, included_scopeless


def export_memories(*, path: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    provider_name, records, scoped_passes, included_scopeless = _collect_export_records()
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True, default=str))
            handle.write("\n")
    return {
        "path": str(target.resolve()),
        "provider": provider_name,
        "exported": len(records),
        "scoped_passes": scoped_passes,
        "included_scopeless": included_scopeless,
        "format": "jsonl",
    }


def _import_metadata(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("metadata")
    if raw is None:
        metadata: dict[str, Any] = {}
    elif isinstance(raw, dict):
        metadata = dict(raw)
    else:
        raise ProviderValidationError("Imported memory metadata must be a JSON object.")

    existing_source = metadata.get("source")
    if existing_source not in (None, "import") and "import_original_source" not in metadata:
        metadata["import_original_source"] = existing_source
    metadata["source"] = "import"

    imported_provider = record.get("provider")
    if isinstance(imported_provider, str) and imported_provider:
        metadata.setdefault("import_provider", imported_provider)
    imported_memory_id = record.get("id")
    if isinstance(imported_memory_id, str) and imported_memory_id:
        metadata.setdefault("imported_memory_id", imported_memory_id)
    created_at = record.get("created_at")
    if isinstance(created_at, str) and created_at:
        metadata.setdefault("imported_created_at", created_at)
    updated_at = record.get("updated_at")
    if isinstance(updated_at, str) and updated_at:
        metadata.setdefault("imported_updated_at", updated_at)
    return metadata


def import_memories(*, path: str) -> dict[str, Any]:
    source = Path(path).expanduser()
    if not source.exists():
        raise ProviderValidationError(f"Import file not found: {source}")

    imported = 0
    with source.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProviderValidationError(f"Invalid JSON on line {line_number}: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise ProviderValidationError(f"Imported line {line_number} must decode to an object.")
            memory_text = record.get("memory")
            if not isinstance(memory_text, str) or not memory_text.strip():
                raise ProviderValidationError(f"Imported line {line_number} is missing a non-empty 'memory' field.")
            memory_add(
                messages=[{"role": "user", "content": memory_text}],
                user_id=record.get("user_id"),
                agent_id=record.get("agent_id"),
                run_id=record.get("run_id"),
                metadata=_import_metadata(record),
                infer=False,
                memory_type=record.get("memory_type"),
            )
            imported += 1

    return {
        "path": str(source.resolve()),
        "provider": active_provider_name(),
        "imported": imported,
        "format": "jsonl",
    }
