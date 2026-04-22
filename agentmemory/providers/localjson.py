from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from agentmemory.providers.base import (
    BaseMemoryProvider,
    DeleteResult,
    MemoryNotFoundError,
    MemoryPage,
    ProviderContract,
    MemoryRecord,
    ProviderCapabilityError,
    ProviderCapabilities,
    ProviderRuntimePolicy,
    ProviderValidationError,
    ScopeInventory,
)
from agentmemory.runtime import scope_registry


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
            "supports_pagination": True,
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

    @contextlib.contextmanager
    def _file_lock(self):
        self._ensure_parent()
        lock_path = self.storage_path.with_suffix(self.storage_path.suffix + ".lock")
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

    def _load_all_unlocked(self) -> list[dict[str, Any]]:
        self._ensure_parent()
        if not self.storage_path.exists():
            return []
        return json.loads(self.storage_path.read_text(encoding="utf-8"))

    def _save_all_unlocked(self, records: list[dict[str, Any]]) -> None:
        self._ensure_parent()
        body = json.dumps(records, ensure_ascii=True, indent=2) + "\n"
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.storage_path.parent,
                prefix=f".{self.storage_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = temp_file.name
                temp_file.write(body)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, self.storage_path)
            temp_path = None
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)

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

    def _sync_scope_registry_upsert(self, *, operation: str, record: MemoryRecord) -> None:
        memory_id = str(record.get("id", "")) or None
        try:
            scope_registry.upsert_record(self.provider_name, record, self.runtime_dir)
        except Exception as exc:
            try:
                scope_registry.mark_sync_failed(
                    self.provider_name,
                    self.runtime_dir,
                    operation=operation,
                    memory_id=memory_id,
                    error=exc,
                )
            except Exception:
                pass
        else:
            try:
                scope_registry.clear_sync_failure(self.provider_name, self.runtime_dir)
            except Exception:
                pass

    def _sync_scope_registry_delete(self, *, operation: str, memory_id: str) -> None:
        try:
            scope_registry.delete_record(self.provider_name, memory_id, self.runtime_dir)
        except Exception as exc:
            try:
                scope_registry.mark_sync_failed(
                    self.provider_name,
                    self.runtime_dir,
                    operation=operation,
                    memory_id=memory_id,
                    error=exc,
                )
            except Exception:
                pass
        else:
            try:
                scope_registry.clear_sync_failure(self.provider_name, self.runtime_dir)
            except Exception:
                pass

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
            with self._file_lock():
                records = self._load_all_unlocked()
                records.append(record)
                self._save_all_unlocked(records)
        public = self._public_record(record)
        self._sync_scope_registry_upsert(operation="add", record=public)
        return public

    def search_memory(self, *, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True) -> list[MemoryRecord]:
        return self.search_memory_page(
            query=query,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            limit=limit,
            cursor=None,
            filters=filters,
            threshold=threshold,
            rerank=rerank,
        )["items"]

    def search_memory_page(
        self,
        *,
        query,
        user_id=None,
        agent_id=None,
        run_id=None,
        limit=10,
        cursor=None,
        filters=None,
        threshold=None,
        rerank=True,
    ) -> MemoryPage:
        if rerank:
            raise ProviderCapabilityError("Local JSON provider does not support rerank.")
        try:
            offset = int(cursor) if cursor is not None else 0
        except (TypeError, ValueError) as exc:
            raise ProviderValidationError("Invalid Local JSON pagination cursor.") from exc
        if offset < 0:
            raise ProviderValidationError("Invalid Local JSON pagination cursor.")
        page_limit = max(int(limit), 1)
        results: list[dict[str, Any]] = []
        with self._lock:
            with self._file_lock():
                records = self._load_all_unlocked()
            for record in records:
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
        page = results[offset : offset + page_limit]
        next_offset = offset + len(page)
        return {
            "provider": self.provider_name,
            "items": page,
            "next_cursor": str(next_offset) if next_offset < len(results) else None,
            "pagination_supported": True,
        }

    def list_memories(self, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None) -> list[MemoryRecord]:
        return self.list_memories_page(
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            limit=limit,
            cursor=None,
            filters=filters,
        )["items"]

    def list_memories_page(self, *, user_id=None, agent_id=None, run_id=None, limit=100, cursor=None, filters=None) -> MemoryPage:
        try:
            offset = int(cursor) if cursor is not None else 0
        except (TypeError, ValueError) as exc:
            raise ProviderValidationError("Invalid Local JSON pagination cursor.") from exc
        if offset < 0:
            raise ProviderValidationError("Invalid Local JSON pagination cursor.")
        page_limit = max(int(limit), 1)
        with self._lock:
            with self._file_lock():
                raw_records = self._load_all_unlocked()
            records = [
                self._public_record(record)
                for record in raw_records
                if self._matches_scope(record, user_id=user_id, agent_id=agent_id, run_id=run_id) and self._matches_filters(record, filters)
            ]
        records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        page = records[offset : offset + page_limit]
        next_offset = offset + len(page)
        return {
            "provider": self.provider_name,
            "items": page,
            "next_cursor": str(next_offset) if next_offset < len(records) else None,
            "pagination_supported": True,
        }

    def get_memory(self, memory_id):
        with self._lock:
            with self._file_lock():
                records = self._load_all_unlocked()
            for record in records:
                if record.get("id") == memory_id:
                    return self._public_record(record)
        raise MemoryNotFoundError(memory_id)

    def update_memory(self, *, memory_id, data, metadata=None) -> MemoryRecord:
        with self._lock:
            with self._file_lock():
                records = self._load_all_unlocked()
                for record in records:
                    if record.get("id") == memory_id:
                        record["memory"] = data
                        if metadata is not None:
                            record["metadata"] = metadata
                        record["updated_at"] = utc_now()
                        self._save_all_unlocked(records)
                        public = self._public_record(record)
                        break
                else:
                    raise MemoryNotFoundError(memory_id)
        self._sync_scope_registry_upsert(operation="update", record=public)
        return public

    def delete_memory(self, *, memory_id) -> DeleteResult:
        with self._lock:
            with self._file_lock():
                records = self._load_all_unlocked()
                remaining = [record for record in records if record.get("id") != memory_id]
                if len(remaining) == len(records):
                    raise MemoryNotFoundError(memory_id)
                self._save_all_unlocked(remaining)
        self._sync_scope_registry_delete(operation="delete", memory_id=str(memory_id))
        return {"id": memory_id, "deleted": True, "provider": self.provider_name}

    def list_scopes(self, *, limit: int = 200, kind: str | None = None, query: str | None = None) -> ScopeInventory:
        return scope_registry.list_inventory(self.provider_name, limit, kind, query, self.runtime_dir)

    def iter_scope_registry_seed_records(self) -> list[MemoryRecord]:
        with self._lock:
            with self._file_lock():
                records = self._load_all_unlocked()
        return [self._public_record(record) for record in records]
