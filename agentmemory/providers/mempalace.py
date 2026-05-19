from __future__ import annotations

import importlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from agentmemory.providers.base import (
    BaseMemoryProvider,
    DeleteResult,
    MemoryNotFoundError,
    MemoryRecord,
    ProviderCapabilities,
    ProviderCapabilityError,
    ProviderContract,
    ProviderRuntimePolicy,
    ProviderUnavailableError,
    ProviderValidationError,
    ScopeInventory,
)
from agentmemory.runtime import scope_registry


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_mempalace_api() -> SimpleNamespace:
    package = importlib.import_module("mempalace")
    palace_module = importlib.import_module("mempalace.palace")
    base_module = importlib.import_module("mempalace.backends.base")
    try:
        version = importlib.metadata.version("mempalace")
    except importlib.metadata.PackageNotFoundError:
        version = getattr(package, "__version__", "unknown")
    return SimpleNamespace(
        version=version,
        get_collection=palace_module.get_collection,
        palace_not_found_error=base_module.PalaceNotFoundError,
        backend_error=base_module.BackendError,
    )


class MemPalaceProvider(BaseMemoryProvider):
    provider_name = "mempalace"
    display_name = "MemPalace"
    summary = "Experimental local semantic provider backed by an AgentMemory-owned MemPalace collection."
    certification_status = "experimental"
    certification_harness_classes = ("test_mempalace_provider.MemPalaceProviderHarnessTests",)
    certification_related_test_modules = (
        "test_mempalace_provider",
        "test_agentmemory_runtime",
    )
    onboarding_order = 40

    @classmethod
    def default_provider_config(cls, *, runtime_dir: str) -> dict[str, Any]:
        runtime_path = Path(runtime_dir)
        return {
            "palace_path": str(runtime_path / "mempalace-palace"),
            "palace_id": "agentmemory",
            "collection_name": "agentmemory_records",
            "default_limit": 100,
        }

    @classmethod
    def install_requirements(cls) -> list[str]:
        return ["mempalace==3.3.5"]

    @classmethod
    def configure_parser(cls, parser) -> None:
        if "--palace-path" not in parser._option_string_actions:
            parser.add_argument("--palace-path", help="Override the MemPalace palace path for the mempalace provider")
        if "--palace-id" not in parser._option_string_actions:
            parser.add_argument("--palace-id", help="Override the AgentMemory-owned MemPalace palace identifier")
        if "--collection-name" not in parser._option_string_actions:
            parser.add_argument("--collection-name", help="Override the MemPalace collection name for AgentMemory records")

    @classmethod
    def apply_cli_configuration(cls, *, provider_config: dict[str, Any], args) -> bool:
        changed = False
        if getattr(args, "palace_path", None):
            provider_config["palace_path"] = args.palace_path
            changed = True
        if getattr(args, "palace_id", None):
            provider_config["palace_id"] = args.palace_id
            changed = True
        if getattr(args, "collection_name", None):
            provider_config["collection_name"] = args.collection_name
            changed = True
        return changed

    def __init__(self, *, runtime_config: dict[str, Any], provider_config: dict[str, Any]) -> None:
        super().__init__(runtime_config=runtime_config, provider_config=provider_config)
        self._lock = Lock()

    @property
    def palace_path(self) -> Path:
        return Path(self.provider_config.get("palace_path") or "").expanduser().resolve()

    @property
    def palace_id(self) -> str:
        value = str(self.provider_config.get("palace_id") or "agentmemory").strip()
        return value or "agentmemory"

    @property
    def collection_name(self) -> str:
        value = str(self.provider_config.get("collection_name") or "agentmemory_records").strip()
        return value or "agentmemory_records"

    @property
    def default_limit(self) -> int:
        return self._coerce_limit(self.provider_config.get("default_limit", 100), default=100)

    def capabilities(self) -> ProviderCapabilities:
        return {
            "supports_semantic_search": True,
            "supports_text_search": False,
            "supports_filters": False,
            "supports_metadata_filters": False,
            "supports_rerank": False,
            "supports_update": False,
            "supports_delete": True,
            "supports_scopeless_list": True,
            "requires_scope_for_list": False,
            "requires_scope_for_search": False,
            "supports_owner_process_mode": False,
            "supports_scope_inventory": True,
            "supports_pagination": False,
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
            "filter_semantics": "provider_defined",
            "metadata_value_policy": "json_object",
            "supports_background_ingest": False,
            "supports_remote_transport": False,
        }

    def _coerce_limit(self, value: Any, *, default: int) -> int:
        try:
            limit = int(default if value is None else value)
        except (TypeError, ValueError) as exc:
            raise ProviderValidationError("Invalid limit for MemPalace provider.") from exc
        return max(limit, 1)

    def _normalized_messages(self, messages) -> str:
        parts: list[str] = []
        for item in messages:
            content = item.get("content") if isinstance(item, dict) else str(item)
            if content:
                parts.append(str(content))
        return "\n".join(parts).strip()

    def _require_no_filters(self, filters: dict[str, Any] | None) -> None:
        if filters:
            raise ProviderCapabilityError("MemPalace provider does not support arbitrary filters in Phase 1.")

    def _scope_where(self, *, user_id=None, agent_id=None, run_id=None) -> dict[str, str] | None:
        where: dict[str, str] = {}
        if isinstance(user_id, str) and user_id.strip():
            where["user_id"] = user_id
        if isinstance(agent_id, str) and agent_id.strip():
            where["agent_id"] = agent_id
        if isinstance(run_id, str) and run_id.strip():
            where["run_id"] = run_id
        return where or None

    def _dependency_status(self) -> tuple[bool, str | None, str]:
        try:
            api = _load_mempalace_api()
        except ModuleNotFoundError:
            return False, None, "mempalace package is not installed"
        except Exception as exc:
            return False, None, f"mempalace import failed: {exc}"
        version = str(getattr(api, "version", "unknown"))
        return True, version, f"mempalace {version}"

    def _api(self) -> SimpleNamespace:
        try:
            return _load_mempalace_api()
        except ModuleNotFoundError as exc:
            raise ProviderUnavailableError(
                "MemPalace provider requires the optional dependency `mempalace==3.3.5`."
            ) from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"Failed to initialize MemPalace provider: {exc}") from exc

    def _open_collection(self, *, create: bool):
        api = self._api()
        try:
            return api.get_collection(
                palace_path=str(self.palace_path),
                collection_name=self.collection_name,
                create=create,
            )
        except api.palace_not_found_error:
            if not create:
                return None
            raise
        except api.backend_error as exc:
            raise ProviderUnavailableError(f"MemPalace backend error: {exc}") from exc

    def _load_metadata(self, raw_metadata: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        stored = dict(raw_metadata or {})
        payload = stored.get("agentmemory_metadata_json")
        metadata: dict[str, Any] = {}
        if isinstance(payload, str) and payload.strip():
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                decoded = {}
            if isinstance(decoded, dict):
                metadata = decoded
        return metadata, stored

    def _stored_metadata(
        self,
        *,
        user_id: str | None,
        agent_id: str | None,
        run_id: str | None,
        memory_type: str | None,
        metadata: dict[str, Any],
        created_at: str,
        updated_at: str,
    ) -> dict[str, Any]:
        stored: dict[str, Any] = {
            "agentmemory_managed": True,
            "palace_id": self.palace_id,
            "created_at": created_at,
            "updated_at": updated_at,
            "agentmemory_metadata_json": json.dumps(metadata, ensure_ascii=True, sort_keys=True),
        }
        if isinstance(user_id, str) and user_id.strip():
            stored["user_id"] = user_id
        if isinstance(agent_id, str) and agent_id.strip():
            stored["agent_id"] = agent_id
        if isinstance(run_id, str) and run_id.strip():
            stored["run_id"] = run_id
        if isinstance(memory_type, str) and memory_type.strip():
            stored["memory_type"] = memory_type
        return stored

    def _record_from_backend(
        self,
        *,
        memory_id: str,
        document: Any,
        raw_metadata: Any,
        score: float | None = None,
    ) -> MemoryRecord:
        metadata, stored = self._load_metadata(raw_metadata)
        record: MemoryRecord = {
            "id": memory_id,
            "memory": str(document or ""),
            "metadata": metadata,
            "user_id": stored.get("user_id"),
            "agent_id": stored.get("agent_id"),
            "run_id": stored.get("run_id"),
            "memory_type": stored.get("memory_type"),
            "created_at": stored.get("created_at"),
            "updated_at": stored.get("updated_at"),
            "provider": self.provider_name,
            "raw": {
                "palace_id": self.palace_id,
                "collection_name": self.collection_name,
                "backend_metadata": stored,
            },
        }
        if score is not None:
            record["score"] = score
        return record

    def _sort_records(self, records: list[MemoryRecord]) -> list[MemoryRecord]:
        return sorted(
            records,
            key=lambda item: (
                str(item.get("updated_at") or item.get("created_at") or ""),
                str(item.get("id") or ""),
            ),
            reverse=True,
        )

    def _normalize_score(self, distance: Any) -> float:
        try:
            numeric = float(distance)
        except (TypeError, ValueError):
            return 1.0
        return max(0.0, 2.0 - numeric)

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

    def doctor_rows(self) -> list[tuple[str, str]]:
        available, version, details = self._dependency_status()
        info = self.runtime_info()
        return [
            ("Package", details),
            ("Palace path", str(self.palace_path)),
            ("Palace ID", self.palace_id),
            ("Collection", self.collection_name),
            ("Record count", str(info.get("record_count", 0 if not available else "unknown"))),
            ("Default limit", str(self.default_limit)),
            ("Package version", version or "missing"),
        ]

    def dependency_checks(self) -> list[dict[str, str]]:
        available, version, details = self._dependency_status()
        return [
            {
                "name": "mempalace",
                "ok": "true" if available else "false",
                "details": details,
                "version": version or "",
            }
        ]

    def prerequisite_checks(self) -> list[dict[str, str]]:
        palace_parent = self.palace_path.parent
        ok = palace_parent.exists() or palace_parent.parent.exists()
        return [
            {
                "name": "palace_path",
                "ok": "true" if ok else "false",
                "details": str(self.palace_path),
            }
        ]

    def health(self) -> dict[str, Any]:
        available, _, _ = self._dependency_status()
        return {"ok": available, **self.runtime_info()}

    def runtime_info(self) -> dict[str, Any]:
        available, version, details = self._dependency_status()
        record_count = 0
        palace_exists = self.palace_path.exists()
        if available:
            with self._lock:
                try:
                    collection = self._open_collection(create=False)
                except ProviderUnavailableError:
                    collection = None
                if collection is not None:
                    try:
                        record_count = int(collection.count())
                    except Exception:
                        record_count = 0
        return {
            "package_available": available,
            "package_version": version,
            "package_details": details,
            "palace_path": str(self.palace_path),
            "palace_exists": palace_exists,
            "palace_id": self.palace_id,
            "collection_name": self.collection_name,
            "default_limit": self.default_limit,
            "record_count": record_count,
        }

    def add_memory(self, *, messages, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None) -> MemoryRecord:
        del infer
        text = self._normalized_messages(messages)
        if not text:
            raise ProviderValidationError("MemPalace provider requires non-empty memory content.")
        created_at = utc_now()
        updated_at = created_at
        public_metadata = dict(metadata or {})
        memory_id = str(uuid4())
        stored_metadata = self._stored_metadata(
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            memory_type=memory_type,
            metadata=public_metadata,
            created_at=created_at,
            updated_at=updated_at,
        )
        with self._lock:
            collection = self._open_collection(create=True)
            collection.add(
                documents=[text],
                ids=[memory_id],
                metadatas=[stored_metadata],
            )
            hydrated = self._get_memory_or_none(memory_id)
        if hydrated is None:
            raise ProviderUnavailableError("MemPalace provider failed to hydrate a stable record after add.")
        self._sync_scope_registry_upsert(operation="add", record=hydrated)
        return hydrated

    def search_memory(self, *, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True) -> list[MemoryRecord]:
        if rerank:
            raise ProviderCapabilityError("MemPalace provider does not support rerank.")
        self._require_no_filters(filters)
        page_limit = self._coerce_limit(limit, default=self.default_limit)
        with self._lock:
            collection = self._open_collection(create=False)
            if collection is None:
                return []
            result = collection.query(
                query_texts=[str(query)],
                n_results=page_limit,
                where=self._scope_where(user_id=user_id, agent_id=agent_id, run_id=run_id),
                include=["documents", "metadatas", "distances"],
            )
        ids = list(result.ids[0] if getattr(result, "ids", None) else [])
        documents = list(result.documents[0] if getattr(result, "documents", None) else [])
        metadatas = list(result.metadatas[0] if getattr(result, "metadatas", None) else [])
        distances = list(result.distances[0] if getattr(result, "distances", None) else [])
        records: list[MemoryRecord] = []
        for idx, memory_id in enumerate(ids):
            score = self._normalize_score(distances[idx] if idx < len(distances) else None)
            if score < 1.0:
                continue
            if threshold is not None and score < float(threshold):
                continue
            records.append(
                self._record_from_backend(
                    memory_id=str(memory_id),
                    document=documents[idx] if idx < len(documents) else "",
                    raw_metadata=metadatas[idx] if idx < len(metadatas) else {},
                    score=score,
                )
            )
        records.sort(
            key=lambda item: (
                float(item.get("score", 0.0)),
                str(item.get("updated_at") or item.get("created_at") or ""),
                str(item.get("id") or ""),
            ),
            reverse=True,
        )
        return records[:page_limit]

    def list_memories(self, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None) -> list[MemoryRecord]:
        self._require_no_filters(filters)
        page_limit = self._coerce_limit(limit, default=self.default_limit)
        with self._lock:
            collection = self._open_collection(create=False)
            if collection is None:
                return []
            result = collection.get(
                where=self._scope_where(user_id=user_id, agent_id=agent_id, run_id=run_id),
                include=["documents", "metadatas"],
            )
        ids = list(getattr(result, "ids", []) or [])
        documents = list(getattr(result, "documents", []) or [])
        metadatas = list(getattr(result, "metadatas", []) or [])
        records = [
            self._record_from_backend(
                memory_id=str(memory_id),
                document=documents[idx] if idx < len(documents) else "",
                raw_metadata=metadatas[idx] if idx < len(metadatas) else {},
            )
            for idx, memory_id in enumerate(ids)
        ]
        return self._sort_records(records)[:page_limit]

    def _get_memory_or_none(self, memory_id: str) -> MemoryRecord | None:
        collection = self._open_collection(create=False)
        if collection is None:
            return None
        result = collection.get(ids=[memory_id], include=["documents", "metadatas"])
        ids = list(getattr(result, "ids", []) or [])
        if not ids:
            return None
        documents = list(getattr(result, "documents", []) or [])
        metadatas = list(getattr(result, "metadatas", []) or [])
        return self._record_from_backend(
            memory_id=str(ids[0]),
            document=documents[0] if documents else "",
            raw_metadata=metadatas[0] if metadatas else {},
        )

    def get_memory(self, memory_id) -> MemoryRecord:
        with self._lock:
            record = self._get_memory_or_none(str(memory_id))
        if record is None:
            raise MemoryNotFoundError(str(memory_id))
        return record

    def delete_memory(self, *, memory_id) -> DeleteResult:
        memory_key = str(memory_id)
        with self._lock:
            record = self._get_memory_or_none(memory_key)
            if record is None:
                raise MemoryNotFoundError(memory_key)
            collection = self._open_collection(create=False)
            if collection is None:
                raise MemoryNotFoundError(memory_key)
            collection.delete(ids=[memory_key])
        self._sync_scope_registry_delete(operation="delete", memory_id=memory_key)
        return {"id": memory_key, "deleted": True, "provider": self.provider_name}

    def list_scopes(self, *, limit: int = 200, kind: str | None = None, query: str | None = None) -> ScopeInventory:
        page_limit = self._coerce_limit(limit, default=200)
        return scope_registry.list_inventory(self.provider_name, page_limit, kind, query, self.runtime_dir)

    def iter_scope_registry_seed_records(self) -> list[MemoryRecord]:
        return self.list_memories(limit=max(self.default_limit, 10000))
