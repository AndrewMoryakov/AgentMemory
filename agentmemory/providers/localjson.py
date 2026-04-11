from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from agentmemory.providers.base import (
    BaseMemoryProvider,
    DeleteResult,
    MemoryNotFoundError,
    ProviderContract,
    MemoryRecord,
    ProviderCapabilityError,
    ProviderCapabilities,
    ProviderRuntimePolicy,
    ProviderValidationError,
    ScopeInventory,
    ScopeInventoryItem,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalJsonProvider(BaseMemoryProvider):
    provider_name = "localjson"
    display_name = "Local JSON"
    summary = "Built-in local JSON provider used for contract validation and local demos."
    certification_status = "certified"
    expected_certification_status_code = "certified"
    certification_notes = "Built-in validation provider must stay fully certified."

    @classmethod
    def default_provider_config(cls, *, runtime_dir: str) -> dict[str, Any]:
        runtime_path = Path(runtime_dir)
        return {
            "storage_path": str(runtime_path / "localjson-memories.json"),
            "default_limit": 100,
        }

    @classmethod
    def configure_parser(cls, parser) -> None:
        parser.add_argument("--storage-path", help="Override Local JSON storage path for the localjson provider")

    @classmethod
    def apply_cli_configuration(cls, *, provider_config: dict[str, Any], args) -> bool:
        changed = False
        if getattr(args, "storage_path", None):
            provider_config["storage_path"] = args.storage_path
            changed = True
        return changed

    def __init__(self, *, runtime_config: dict[str, Any], provider_config: dict[str, Any]) -> None:
        super().__init__(runtime_config=runtime_config, provider_config=provider_config)
        self._lock = Lock()

    def capabilities(self) -> ProviderCapabilities:
        return {
            "supports_semantic_search": False,
            "supports_text_search": True,
            "supports_filters": True,
            "supports_metadata_filters": True,
            "supports_rerank": False,
            "supports_update": True,
            "supports_delete": True,
            "supports_scopeless_list": True,
            "requires_scope_for_list": False,
            "requires_scope_for_search": False,
            "supports_owner_process_mode": False,
            "supports_scope_inventory": True,
        }

    def runtime_policy(self) -> ProviderRuntimePolicy:
        return {"transport_mode": "direct"}

    def provider_contract(self) -> ProviderContract:
        return {
            "contract_version": "v2",
            "record_shape": "memory_record_v1",
            "scope_kinds": ["user", "agent", "run"],
            "consistency": "immediate",
            "write_visibility": "immediate",
            "update_semantics": "replace",
            "delete_semantics": "hard_delete",
            "filter_semantics": "record_and_metadata",
            "metadata_value_policy": "json_object",
            "supports_background_ingest": False,
            "supports_remote_transport": False,
        }

    @property
    def storage_path(self) -> Path:
        return Path(self.provider_config["storage_path"])

    def _ensure_parent(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_all(self) -> list[dict[str, Any]]:
        self._ensure_parent()
        if not self.storage_path.exists():
            return []
        return json.loads(self.storage_path.read_text(encoding="utf-8"))

    def _save_all(self, records: list[dict[str, Any]]) -> None:
        self._ensure_parent()
        self.storage_path.write_text(json.dumps(records, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    def _matches_scope(self, record: dict[str, Any], *, user_id=None, agent_id=None, run_id=None) -> bool:
        if user_id is not None and record.get("user_id") != user_id:
            return False
        if agent_id is not None and record.get("agent_id") != agent_id:
            return False
        if run_id is not None and record.get("run_id") != run_id:
            return False
        return True

    def _matches_filters(self, record: dict[str, Any], filters: dict[str, Any] | None) -> bool:
        if not filters:
            return True
        metadata = record.get("metadata") or {}
        for key, expected in filters.items():
            if key in record:
                actual = record.get(key)
            else:
                actual = metadata.get(key)
            if actual != expected:
                return False
        return True

    def _normalized_messages(self, messages) -> str:
        parts: list[str] = []
        for item in messages:
            content = item.get("content") if isinstance(item, dict) else str(item)
            if content:
                parts.append(str(content))
        return "\n".join(parts).strip()

    def _score(self, query: str, text: str) -> float:
        query_l = query.lower().strip()
        text_l = text.lower()
        if not query_l:
            return 0.0
        if query_l in text_l:
            return 1.0
        query_tokens = {token for token in query_l.split() if token}
        if not query_tokens:
            return 0.0
        text_tokens = {token for token in text_l.split() if token}
        overlap = len(query_tokens & text_tokens)
        return overlap / len(query_tokens)

    def _public_record(self, record: dict[str, Any]) -> MemoryRecord:
        return {
            "id": str(record.get("id", "")),
            "memory": str(record.get("memory", "")),
            "metadata": dict(record.get("metadata") or {}),
            "user_id": record.get("user_id"),
            "agent_id": record.get("agent_id"),
            "run_id": record.get("run_id"),
            "memory_type": record.get("memory_type"),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "provider": self.provider_name,
            **({"score": record["score"]} if "score" in record else {}),
            **({"raw": record["raw"]} if "raw" in record else {}),
        }

    def _scope_inventory(self, *, kind: str | None = None, query: str | None = None) -> list[ScopeInventoryItem]:
        kind_map = {"user": "user_id", "agent": "agent_id", "run": "run_id"}
        selected_kinds = [kind] if kind else ["user", "agent", "run"]
        query_l = query.lower() if query else None
        buckets: dict[tuple[str, str], ScopeInventoryItem] = {}

        for record in self._load_all():
            for selected in selected_kinds:
                field_name = kind_map[selected]
                value = record.get(field_name)
                if not isinstance(value, str) or not value.strip():
                    continue
                if query_l and query_l not in value.lower():
                    continue
                key = (selected, value)
                item = buckets.setdefault(
                    key,
                    {"kind": selected, "value": value, "count": 0, "last_seen_at": None},
                )
                item["count"] += 1
                timestamp = record.get("updated_at") or record.get("created_at")
                if isinstance(timestamp, str) and timestamp and (item["last_seen_at"] is None or timestamp > item["last_seen_at"]):
                    item["last_seen_at"] = timestamp

        return sorted(buckets.values(), key=lambda item: (item["kind"], -item["count"], item["value"]))

    def doctor_rows(self) -> list[tuple[str, str]]:
        return [
            ("Storage path", str(self.storage_path)),
            ("Default limit", str(self.provider_config.get("default_limit", 100))),
        ]

    def dependency_checks(self) -> list[dict[str, str]]:
        return [{"name": "python-stdlib", "ok": "true", "details": "built-in"}]

    def prerequisite_checks(self) -> list[dict[str, str]]:
        return [{"name": "storage", "ok": "true", "details": str(self.storage_path)}]

    def health(self) -> dict[str, Any]:
        return {"ok": True, **self.runtime_info()}

    def runtime_info(self) -> dict[str, Any]:
        return {
            "storage_path": str(self.storage_path),
            "storage_exists": self.storage_path.exists(),
            "default_limit": int(self.provider_config.get("default_limit", 100)),
        }

    def add_memory(self, *, messages, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None) -> MemoryRecord:
        text = self._normalized_messages(messages)
        record = {
            "id": str(uuid4()),
            "memory": text,
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "metadata": metadata or {},
            "memory_type": memory_type,
            "infer": infer,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        with self._lock:
            records = self._load_all()
            records.append(record)
            self._save_all(records)
        return self._public_record(record)

    def search_memory(self, *, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True) -> list[MemoryRecord]:
        if rerank:
            raise ProviderCapabilityError("Local JSON provider does not support rerank.")
        results: list[dict[str, Any]] = []
        with self._lock:
            for record in self._load_all():
                if not self._matches_scope(record, user_id=user_id, agent_id=agent_id, run_id=run_id):
                    continue
                if not self._matches_filters(record, filters):
                    continue
                score = self._score(query, record.get("memory", ""))
                if threshold is not None and score < threshold:
                    continue
                if score <= 0:
                    continue
                item = self._public_record(record)
                item["score"] = score
                results.append(item)
        results.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        return results[:limit]

    def list_memories(self, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None) -> list[MemoryRecord]:
        with self._lock:
            records = [
                self._public_record(record)
                for record in self._load_all()
                if self._matches_scope(record, user_id=user_id, agent_id=agent_id, run_id=run_id) and self._matches_filters(record, filters)
            ]
        records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return records[:limit]

    def get_memory(self, memory_id):
        with self._lock:
            for record in self._load_all():
                if record.get("id") == memory_id:
                    return self._public_record(record)
        raise MemoryNotFoundError(memory_id)

    def update_memory(self, *, memory_id, data, metadata=None) -> MemoryRecord:
        with self._lock:
            records = self._load_all()
            for record in records:
                if record.get("id") == memory_id:
                    record["memory"] = data
                    if metadata is not None:
                        record["metadata"] = metadata
                    record["updated_at"] = utc_now()
                    self._save_all(records)
                    return self._public_record(record)
        raise MemoryNotFoundError(memory_id)

    def delete_memory(self, *, memory_id) -> DeleteResult:
        with self._lock:
            records = self._load_all()
            remaining = [record for record in records if record.get("id") != memory_id]
            if len(remaining) == len(records):
                raise MemoryNotFoundError(memory_id)
            self._save_all(remaining)
        return {"id": memory_id, "deleted": True, "provider": self.provider_name}

    def list_scopes(self, *, limit: int = 200, kind: str | None = None, query: str | None = None) -> ScopeInventory:
        if kind not in {None, "user", "agent", "run"}:
            raise ProviderValidationError("Scope kind must be one of: user, agent, run.")
        with self._lock:
            all_items = self._scope_inventory(kind=None, query=query)
            items = self._scope_inventory(kind=kind, query=query)
        totals = {
            "users": sum(1 for item in all_items if item["kind"] == "user"),
            "agents": sum(1 for item in all_items if item["kind"] == "agent"),
            "runs": sum(1 for item in all_items if item["kind"] == "run"),
        }
        return {"provider": self.provider_name, "items": items[:limit], "totals": totals}
