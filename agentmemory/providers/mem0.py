from __future__ import annotations

import os
import sys
from functools import lru_cache
import importlib.metadata
import pickle
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any

from mem0 import Memory
try:
    from mem0.exceptions import ConfigurationError as Mem0ConfigurationError
    from mem0.exceptions import MemoryNotFoundError as Mem0MemoryNotFoundError
except Exception:  # pragma: no cover
    Mem0ConfigurationError = RuntimeError  # type: ignore[assignment]
    Mem0MemoryNotFoundError = LookupError  # type: ignore[assignment]

from agentmemory.providers.base import (
    BaseMemoryProvider,
    DeleteResult,
    MemoryNotFoundError,
    MemoryRecord,
    ProviderCapabilityError,
    ProviderCapabilities,
    ProviderContract,
    ProviderConfigurationError,
    ProviderRuntimePolicy,
    ProviderScopeRequiredError,
    ProviderUnavailableError,
    ProviderValidationError,
    ScopeInventory,
    ScopeInventoryItem,
)


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PLACEHOLDER_KEYS = {"paste-your-openrouter-key-here", "YOUR_OPENROUTER_API_KEY"}


ConfigurationError = ProviderConfigurationError


def is_configured_api_key(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip()
    return bool(normalized) and normalized not in PLACEHOLDER_KEYS


class Mem0Provider(BaseMemoryProvider):
    provider_name = "mem0"
    display_name = "Mem0"
    summary = "Primary semantic provider. Certified at the contract layer through the reusable harness with a fake backend seam."
    certification_status = "certified"
    expected_certification_status_code = "certified_with_skips"
    certification_notes = "Mem0 is expected to certify with one skipped negative-path harness case."

    @classmethod
    def default_provider_config(cls, *, runtime_dir: str) -> dict[str, Any]:
        return {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": "agentmemory_openrouter",
                    "path": runtime_dir.replace("\\", "/") + "/qdrant",
                    "on_disk": True,
                    "embedding_model_dims": 1536,
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": "google/gemma-4-31b-it",
                    "temperature": 0.1,
                    "max_tokens": 1500,
                    "top_p": 0.1,
                    "openrouter_base_url": OPENROUTER_BASE_URL,
                    "site_url": "https://local.agentmemory",
                    "app_name": "AgentMemory",
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": "google/gemini-embedding-001",
                    "openai_base_url": OPENROUTER_BASE_URL,
                    "embedding_dims": 1536,
                },
            },
            "history_db_path": runtime_dir.replace("\\", "/") + "/history.db",
        }

    @classmethod
    def install_requirements(cls) -> list[str]:
        return ["mem0ai==1.0.10"]

    @classmethod
    def configure_parser(cls, parser) -> None:
        parser.add_argument("--openrouter-api-key", help="Store OPENROUTER_API_KEY in .env")
        parser.add_argument("--llm-model")
        parser.add_argument("--embedding-model")
        parser.add_argument("--embedding-dims", type=int)
        parser.add_argument("--collection-name")
        parser.add_argument("--site-url")
        parser.add_argument("--app-name")

    @classmethod
    def env_updates_from_args(cls, args) -> dict[str, str]:
        updates: dict[str, str] = {}
        if getattr(args, "openrouter_api_key", None):
            updates["OPENROUTER_API_KEY"] = args.openrouter_api_key
        return updates

    @classmethod
    def apply_cli_configuration(cls, *, provider_config: dict[str, Any], args) -> bool:
        changed = False
        if args.llm_model:
            provider_config["llm"]["config"]["model"] = args.llm_model
            changed = True
        if args.embedding_model:
            provider_config["embedder"]["config"]["model"] = args.embedding_model
            changed = True
        if args.embedding_dims is not None:
            provider_config["embedder"]["config"]["embedding_dims"] = args.embedding_dims
            provider_config["vector_store"]["config"]["embedding_model_dims"] = args.embedding_dims
            changed = True
        if args.collection_name:
            provider_config["vector_store"]["config"]["collection_name"] = args.collection_name
            changed = True
        if args.site_url:
            provider_config["llm"]["config"]["site_url"] = args.site_url
            changed = True
        if args.app_name:
            provider_config["llm"]["config"]["app_name"] = args.app_name
            changed = True
        return changed

    def __init__(self, *, runtime_config: dict[str, Any], provider_config: dict[str, Any]) -> None:
        super().__init__(runtime_config=runtime_config, provider_config=provider_config)
        self._memory_lock = Lock()

    def capabilities(self) -> ProviderCapabilities:
        return {
            "supports_semantic_search": True,
            "supports_text_search": False,
            "supports_filters": True,
            "supports_metadata_filters": True,
            "supports_rerank": True,
            "supports_update": True,
            "supports_delete": True,
            "supports_scopeless_list": False,
            "requires_scope_for_list": True,
            "requires_scope_for_search": True,
            "supports_owner_process_mode": True,
            "supports_scope_inventory": True,
        }

    def runtime_policy(self) -> ProviderRuntimePolicy:
        return {"transport_mode": "owner_process_proxy"}

    def provider_contract(self) -> ProviderContract:
        return {
            "contract_version": "v2",
            "record_shape": "memory_record_v1",
            "scope_kinds": ["user", "agent", "run"],
            "consistency": "immediate",
            "write_visibility": "owner_process_proxy",
            "update_semantics": "replace",
            "delete_semantics": "provider_defined",
            "filter_semantics": "record_and_metadata",
            "metadata_value_policy": "json_object",
            "supports_background_ingest": False,
            "supports_remote_transport": False,
        }

    def clear_caches(self) -> None:
        self._get_openrouter_api_key.cache_clear()
        self._load_memory.cache_clear()

    @lru_cache(maxsize=1)
    def _get_openrouter_api_key(self) -> str:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not is_configured_api_key(api_key):
            raise ProviderConfigurationError(
                "OPENROUTER_API_KEY is not set. Put it in the shell or in AgentMemory/.env"
            )
        return api_key

    @lru_cache(maxsize=1)
    def _load_memory(self) -> Memory:
        api_key = self._get_openrouter_api_key()
        os.environ.setdefault("OPENAI_API_KEY", api_key)
        os.environ.setdefault("OPENAI_BASE_URL", OPENROUTER_BASE_URL)

        config = dict(self.provider_config)
        embedder = dict(config.get("embedder", {}))
        embedder_config = dict(embedder.get("config", {}))
        embedder_config["api_key"] = api_key
        embedder["config"] = embedder_config
        config["embedder"] = embedder
        return Memory.from_config(config)

    def _normalize_record(self, payload: dict[str, Any], *, include_score: bool = False) -> MemoryRecord:
        if not isinstance(payload, dict):
            raise ProviderValidationError("Mem0 returned a non-object memory payload.")

        memory_id = payload.get("id") or payload.get("memory_id")
        if not memory_id:
            raise ProviderValidationError("Mem0 returned a memory payload without an id.")

        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        record: MemoryRecord = {
            "id": str(memory_id),
            "memory": str(
                payload.get("memory")
                or payload.get("text")
                or payload.get("data")
                or payload.get("content")
                or ""
            ),
            "metadata": metadata,
            "user_id": payload.get("user_id"),
            "agent_id": payload.get("agent_id"),
            "run_id": payload.get("run_id"),
            "memory_type": payload.get("memory_type"),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
            "provider": self.provider_name,
        }
        if include_score and payload.get("score") is not None:
            try:
                record["score"] = float(payload["score"])
            except (TypeError, ValueError):
                pass

        known_keys = {
            "id",
            "memory_id",
            "memory",
            "text",
            "data",
            "content",
            "metadata",
            "user_id",
            "agent_id",
            "run_id",
            "memory_type",
            "created_at",
            "updated_at",
            "score",
        }
        raw = {key: value for key, value in payload.items() if key not in known_keys}
        if raw:
            record["raw"] = raw
        return record

    def _normalize_records(self, payload: Any, *, include_score: bool = False) -> list[MemoryRecord]:
        if isinstance(payload, list):
            return [self._normalize_record(item, include_score=include_score) for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            if isinstance(payload.get("results"), list):
                return [self._normalize_record(item, include_score=include_score) for item in payload["results"] if isinstance(item, dict)]
            return [self._normalize_record(payload, include_score=include_score)]
        return []

    def _normalize_one_record(self, payload: Any, *, include_score: bool = False) -> MemoryRecord:
        records = self._normalize_records(payload, include_score=include_score)
        if not records:
            raise ProviderValidationError("Mem0 returned an empty or invalid memory payload.")
        return records[0]

    def _coerce_mem0_results(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            if isinstance(payload.get("results"), list):
                return [item for item in payload["results"] if isinstance(item, dict)]
            return [payload]
        return []

    def _looks_like_success_message(self, payload: Any, *, verb: str) -> bool:
        if not isinstance(payload, dict):
            return False
        message = payload.get("message")
        if not isinstance(message, str):
            return False
        normalized = message.strip().lower()
        return verb in normalized and "success" in normalized

    def _record_needs_hydration(self, record: MemoryRecord) -> bool:
        return not any(
            (
                record.get("metadata"),
                record.get("user_id") is not None,
                record.get("agent_id") is not None,
                record.get("run_id") is not None,
                record.get("created_at"),
                record.get("updated_at"),
                record.get("memory_type"),
            )
        )

    def _fallback_added_record(
        self,
        *,
        memory: Memory,
        user_id=None,
        agent_id=None,
        run_id=None,
        metadata=None,
        memory_type=None,
    ) -> MemoryRecord:
        payload = memory.get_all(user_id=user_id, agent_id=agent_id, run_id=run_id, limit=25, filters=None)
        records = self._normalize_records(payload)
        if metadata:
            filtered = [
                record
                for record in records
                if all(record.get("metadata", {}).get(key) == value for key, value in metadata.items())
            ]
            if filtered:
                records = filtered
        if memory_type is not None:
            typed = [
                record
                for record in records
                if record.get("memory_type") == memory_type
                or record.get("metadata", {}).get("memory_type") == memory_type
            ]
            if typed:
                records = typed
        if not records:
            raise ProviderValidationError("Mem0 add succeeded without returning a usable record, and fallback lookup found nothing.")
        return records[0]

    def _normalize_add_result(
        self,
        payload: Any,
        *,
        memory: Memory,
        user_id=None,
        agent_id=None,
        run_id=None,
        metadata=None,
        memory_type=None,
    ) -> MemoryRecord:
        try:
            record = self._normalize_one_record(payload)
        except ProviderValidationError:
            results = self._coerce_mem0_results(payload)
            if results:
                for item in results:
                    if item.get("event") in {"ADD", "UPDATE"} and (item.get("id") or item.get("memory_id")):
                        record = self._normalize_record(item)
                        if self._record_needs_hydration(record):
                            try:
                                hydrated = self._normalize_one_record(memory.get(record["id"]))
                                if "raw" in record and isinstance(record["raw"], dict):
                                    merged_raw = dict(hydrated.get("raw", {}))
                                    merged_raw.update(record["raw"])
                                    hydrated["raw"] = merged_raw
                                return hydrated
                            except Exception as exc:
                                print(f"[agentmemory] hydration failed for {record['id']}: {exc}", file=sys.stderr)
                                return record
                        return record
            return self._fallback_added_record(
                memory=memory,
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
                metadata=metadata,
                memory_type=memory_type,
            )
        if self._record_needs_hydration(record):
            try:
                hydrated = self._normalize_one_record(memory.get(record["id"]))
                if "raw" in record and isinstance(record["raw"], dict):
                    merged_raw = dict(hydrated.get("raw", {}))
                    merged_raw.update(record["raw"])
                    hydrated["raw"] = merged_raw
                return hydrated
            except Exception as exc:
                print(f"[agentmemory] hydration failed for {record['id']}: {exc}", file=sys.stderr)
                return record
        return record

    def _normalize_delete_result(self, payload: Any, *, memory_id: str) -> DeleteResult:
        if not isinstance(payload, dict):
            raise ProviderValidationError("Mem0 returned an invalid delete response.")
        if "id" not in payload or "deleted" not in payload:
            raise ProviderValidationError("Mem0 returned a delete response without required fields.")
        return {
            "id": str(payload["id"]),
            "deleted": bool(payload["deleted"]),
            "provider": self.provider_name,
        }

    def _scope_kind_field(self, kind: str) -> str:
        field_map = {"user": "user_id", "agent": "agent_id", "run": "run_id"}
        if kind not in field_map:
            raise ProviderValidationError("Scope kind must be one of: user, agent, run.")
        return field_map[kind]

    def _qdrant_sqlite_path(self) -> Path:
        config = self.provider_config.get("vector_store", {}).get("config", {})
        base_path = Path(str(config.get("path", "")))
        collection_name = str(config.get("collection_name", ""))
        sqlite_path = base_path / "collection" / collection_name / "storage.sqlite"
        if not sqlite_path.exists():
            raise ProviderUnavailableError(f"Mem0 storage is not available at {sqlite_path}")
        return sqlite_path

    def _iter_scope_payloads(self) -> list[dict[str, Any]]:
        sqlite_path = self._qdrant_sqlite_path()
        try:
            connection = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True)
            try:
                rows = connection.execute("SELECT point FROM points").fetchall()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise ProviderUnavailableError(f"Unable to inspect Mem0 scope inventory from {sqlite_path}: {exc}") from exc

        payloads: list[dict[str, Any]] = []
        for (blob,) in rows:
            if not isinstance(blob, (bytes, bytearray)):
                continue
            try:
                point = pickle.loads(blob)
            except Exception:
                continue
            payload = getattr(point, "payload", None)
            if isinstance(payload, dict):
                payloads.append(payload)
        return payloads

    def list_scopes(self, *, limit: int = 200, kind: str | None = None, query: str | None = None) -> ScopeInventory:
        all_kinds = ["user", "agent", "run"]
        if kind is not None:
            self._scope_kind_field(kind)
        selected_kinds = [kind] if kind else all_kinds
        field_map = {selected: self._scope_kind_field(selected) for selected in all_kinds}
        query_l = query.lower() if query else None
        buckets: dict[tuple[str, str], ScopeInventoryItem] = {}

        with self._memory_lock:
            payloads = self._iter_scope_payloads()

        for payload in payloads:
            for selected_kind, field_name in field_map.items():
                value = payload.get(field_name)
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
                timestamp = payload.get("updated_at") or payload.get("created_at")
                if isinstance(timestamp, str) and timestamp and (item["last_seen_at"] is None or timestamp > item["last_seen_at"]):
                    item["last_seen_at"] = timestamp

        all_items = sorted(buckets.values(), key=lambda item: (item["kind"], -item["count"], item["value"]))
        items = [item for item in all_items if item["kind"] in selected_kinds]
        totals = {
            "users": sum(1 for item in all_items if item["kind"] == "user"),
            "agents": sum(1 for item in all_items if item["kind"] == "agent"),
            "runs": sum(1 for item in all_items if item["kind"] == "run"),
        }
        return {"provider": self.provider_name, "items": items[:limit], "totals": totals}

    @staticmethod
    def _message_indicates_scope_required(message: str) -> bool:
        lower = message.lower()
        scope_keywords = ("user_id", "agent_id", "run_id")
        return any(kw in lower for kw in scope_keywords) and (
            "must be provided" in lower or "required" in lower
        )

    @staticmethod
    def _message_indicates_qdrant_lock(message: str) -> bool:
        lower = message.lower()
        return "qdrant" in lower and (
            "already accessed" in lower or "another instance" in lower or "locked" in lower
        )

    def _map_exception(self, exc: Exception) -> Exception:
        if isinstance(exc, ProviderConfigurationError):
            return exc
        if isinstance(exc, MemoryNotFoundError):
            return exc
        if isinstance(exc, Mem0MemoryNotFoundError):
            return MemoryNotFoundError(str(exc))
        if isinstance(exc, Mem0ConfigurationError):
            return ProviderConfigurationError(str(exc))

        message = str(exc)
        if self._message_indicates_scope_required(message):
            return ProviderScopeRequiredError(message)
        if self._message_indicates_qdrant_lock(message):
            return ProviderUnavailableError(message)
        if isinstance(exc, ProviderValidationError):
            return exc
        return ProviderUnavailableError(message)

    def health(self) -> dict[str, Any]:
        return {"ok": True, **self.runtime_info()}

    def runtime_info(self) -> dict[str, Any]:
        return {
            "llm_model": self.provider_config["llm"]["config"]["model"],
            "embedding_model": self.provider_config["embedder"]["config"]["model"],
            "embedding_dims": self.provider_config["embedder"]["config"]["embedding_dims"],
            "vector_store": self.provider_config["vector_store"]["provider"],
            "openrouter_key_present": is_configured_api_key(os.environ.get("OPENROUTER_API_KEY")),
        }

    def doctor_rows(self) -> list[tuple[str, str]]:
        return [
            ("LLM model", str(self.provider_config["llm"]["config"]["model"])),
            ("Embedding model", str(self.provider_config["embedder"]["config"]["model"])),
            ("Embedding dims", str(self.provider_config["embedder"]["config"]["embedding_dims"])),
            ("Vector store", str(self.provider_config["vector_store"]["provider"])),
        ]

    def dependency_checks(self) -> list[dict[str, str]]:
        checks: list[dict[str, str]] = []
        for requirement in self.install_requirements():
            package_name = requirement.split("==", 1)[0]
            try:
                version = importlib.metadata.version(package_name)
                checks.append({"name": package_name, "ok": "true", "details": version})
            except importlib.metadata.PackageNotFoundError:
                checks.append({"name": package_name, "ok": "false", "details": "not installed"})
        return checks

    def prerequisite_checks(self) -> list[dict[str, str]]:
        return [
            {
                "name": "OPENROUTER_API_KEY",
                "ok": "true" if is_configured_api_key(os.environ.get("OPENROUTER_API_KEY")) else "false",
                "details": "available" if is_configured_api_key(os.environ.get("OPENROUTER_API_KEY")) else "missing",
            }
        ]

    def add_memory(self, *, messages, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None) -> MemoryRecord:
        if not messages:
            raise ProviderValidationError("Messages must be a non-empty list.")
        with self._memory_lock:
            try:
                memory = self._load_memory()
                payload = memory.add(
                    messages,
                    user_id=user_id,
                    agent_id=agent_id,
                    run_id=run_id,
                    metadata=metadata,
                    infer=infer,
                    memory_type=memory_type,
                )
            except Exception as exc:
                raise self._map_exception(exc) from exc
            return self._normalize_add_result(
                payload,
                memory=memory,
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
                metadata=metadata,
                memory_type=memory_type,
            )

    def search_memory(self, *, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True) -> list[MemoryRecord]:
        if not self.capabilities()["supports_rerank"] and rerank:
            raise ProviderCapabilityError("Mem0 provider does not support rerank.")
        with self._memory_lock:
            try:
                memory = self._load_memory()
                payload = memory.search(
                    query,
                    user_id=user_id,
                    agent_id=agent_id,
                    run_id=run_id,
                    limit=limit,
                    filters=filters,
                    threshold=threshold,
                    rerank=rerank,
                )
            except Exception as exc:
                raise self._map_exception(exc) from exc
            return self._normalize_records(payload, include_score=True)

    def list_memories(self, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None) -> list[MemoryRecord]:
        with self._memory_lock:
            try:
                memory = self._load_memory()
                payload = memory.get_all(
                    user_id=user_id,
                    agent_id=agent_id,
                    run_id=run_id,
                    limit=limit,
                    filters=filters,
                )
            except Exception as exc:
                raise self._map_exception(exc) from exc
            return self._normalize_records(payload)

    def get_memory(self, memory_id) -> MemoryRecord:
        with self._memory_lock:
            try:
                payload = self._load_memory().get(memory_id)
            except Exception as exc:
                raise self._map_exception(exc) from exc
            return self._normalize_one_record(payload)

    def update_memory(self, *, memory_id, data, metadata=None) -> MemoryRecord:
        with self._memory_lock:
            try:
                memory = self._load_memory()
                payload = memory.update(memory_id, data, metadata=metadata)
            except Exception as exc:
                raise self._map_exception(exc) from exc
            if self._looks_like_success_message(payload, verb="update"):
                try:
                    return self._normalize_one_record(memory.get(memory_id))
                except Exception as exc:
                    raise self._map_exception(exc) from exc
            return self._normalize_one_record(payload)

    def delete_memory(self, *, memory_id) -> DeleteResult:
        with self._memory_lock:
            try:
                payload = self._load_memory().delete(memory_id)
            except Exception as exc:
                raise self._map_exception(exc) from exc
            if self._looks_like_success_message(payload, verb="delete"):
                return {
                    "id": str(memory_id),
                    "deleted": True,
                    "provider": self.provider_name,
                }
            return self._normalize_delete_result(payload, memory_id=str(memory_id))
