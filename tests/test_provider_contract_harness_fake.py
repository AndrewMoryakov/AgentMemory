from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
import unittest

from agentmemory.providers.base import (
    BaseMemoryProvider,
    DeleteResult,
    MemoryNotFoundError,
    MemoryRecord,
    ProviderCapabilities,
    ProviderCapabilityError,
    ProviderRuntimePolicy,
    ScopeInventory,
)
from tests.provider_contract_harness import ProviderContractHarness


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryContractProvider(BaseMemoryProvider):
    provider_name = "inmemory-contract"
    display_name = "InMemory Contract"

    @classmethod
    def default_provider_config(cls, *, runtime_dir: str) -> dict[str, str]:
        return {"runtime_dir": runtime_dir}

    @classmethod
    def apply_cli_configuration(cls, *, provider_config: dict, args) -> bool:
        return False

    def __init__(self, *, runtime_config: dict, provider_config: dict) -> None:
        super().__init__(runtime_config=runtime_config, provider_config=provider_config)
        self._records: list[MemoryRecord] = []

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
            "supports_pagination": False,
        }

    def runtime_policy(self) -> ProviderRuntimePolicy:
        return {"transport_mode": "direct"}

    def doctor_rows(self) -> list[tuple[str, str]]:
        return [("Records", str(len(self._records)))]

    def dependency_checks(self) -> list[dict[str, str]]:
        return [{"name": "python-stdlib", "ok": "true", "details": "built-in"}]

    def prerequisite_checks(self) -> list[dict[str, str]]:
        return [{"name": "storage", "ok": "true", "details": "in-memory"}]

    def health(self) -> dict[str, object]:
        return {"ok": True, **self.runtime_info()}

    def runtime_info(self) -> dict[str, object]:
        return {"provider": self.provider_name, "record_count": len(self._records)}

    def _match_scope(self, record: MemoryRecord, *, user_id=None, agent_id=None, run_id=None) -> bool:
        if user_id is not None and record.get("user_id") != user_id:
            return False
        if agent_id is not None and record.get("agent_id") != agent_id:
            return False
        if run_id is not None and record.get("run_id") != run_id:
            return False
        return True

    def _match_filters(self, record: MemoryRecord, filters=None) -> bool:
        if not filters:
            return True
        metadata = record.get("metadata") or {}
        for key, expected in filters.items():
            actual = record.get(key, metadata.get(key))
            if actual != expected:
                return False
        return True

    def add_memory(self, *, messages, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None) -> MemoryRecord:
        text = "\n".join(str(item.get("content", "")) for item in messages if item.get("content")).strip()
        record: MemoryRecord = {
            "id": str(uuid4()),
            "memory": text,
            "metadata": dict(metadata or {}),
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "memory_type": memory_type,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "provider": self.provider_name,
        }
        self._records.append(record)
        return dict(record)

    def search_memory(self, *, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True) -> list[MemoryRecord]:
        if rerank:
            raise ProviderCapabilityError("InMemory Contract provider does not support rerank.")
        query_l = query.lower()
        results: list[MemoryRecord] = []
        for record in self._records:
            if not self._match_scope(record, user_id=user_id, agent_id=agent_id, run_id=run_id):
                continue
            if not self._match_filters(record, filters=filters):
                continue
            if query_l not in str(record.get("memory", "")).lower():
                continue
            item = dict(record)
            item["score"] = 1.0
            if threshold is not None and item["score"] < threshold:
                continue
            results.append(item)
        return results[:limit]

    def list_memories(self, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None) -> list[MemoryRecord]:
        records = [
            dict(record)
            for record in self._records
            if self._match_scope(record, user_id=user_id, agent_id=agent_id, run_id=run_id)
            and self._match_filters(record, filters=filters)
        ]
        records.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return records[:limit]

    def get_memory(self, memory_id) -> MemoryRecord:
        for record in self._records:
            if record.get("id") == memory_id:
                return dict(record)
        raise MemoryNotFoundError(memory_id)

    def update_memory(self, *, memory_id, data, metadata=None) -> MemoryRecord:
        for record in self._records:
            if record.get("id") == memory_id:
                record["memory"] = data
                if metadata is not None:
                    record["metadata"] = dict(metadata)
                record["updated_at"] = utc_now()
                return dict(record)
        raise MemoryNotFoundError(memory_id)

    def delete_memory(self, *, memory_id) -> DeleteResult:
        for idx, record in enumerate(self._records):
            if record.get("id") == memory_id:
                del self._records[idx]
                return {"id": str(memory_id), "deleted": True, "provider": self.provider_name}
        raise MemoryNotFoundError(memory_id)

    def list_scopes(self, *, limit: int = 200, kind: str | None = None, query: str | None = None) -> ScopeInventory:
        buckets: dict[tuple[str, str], dict[str, object]] = {}
        field_map = {"user": "user_id", "agent": "agent_id", "run": "run_id"}
        selected = [kind] if kind else ["user", "agent", "run"]
        query_l = query.lower() if query else None
        for record in self._records:
            for scope_kind in selected:
                field_name = field_map[scope_kind]
                value = record.get(field_name)
                if not isinstance(value, str) or not value.strip():
                    continue
                if query_l and query_l not in value.lower():
                    continue
                key = (scope_kind, value)
                item = buckets.setdefault(
                    key,
                    {"kind": scope_kind, "value": value, "count": 0, "last_seen_at": None},
                )
                item["count"] = int(item["count"]) + 1
                timestamp = record.get("updated_at") or record.get("created_at")
                if isinstance(timestamp, str) and timestamp and (
                    item["last_seen_at"] is None or timestamp > item["last_seen_at"]
                ):
                    item["last_seen_at"] = timestamp
        items = sorted(buckets.values(), key=lambda item: (str(item["kind"]), -int(item["count"]), str(item["value"])))
        return {
            "provider": self.provider_name,
            "items": items[:limit],
            "totals": {
                "users": sum(1 for item in items if item["kind"] == "user"),
                "agents": sum(1 for item in items if item["kind"] == "agent"),
                "runs": sum(1 for item in items if item["kind"] == "run"),
            },
        }


class ReadOnlyContractProvider(InMemoryContractProvider):
    provider_name = "readonly-contract"
    display_name = "ReadOnly Contract"

    def capabilities(self) -> ProviderCapabilities:
        capabilities = dict(super().capabilities())
        capabilities["supports_update"] = False
        capabilities["supports_delete"] = False
        return capabilities  # type: ignore[return-value]

    def update_memory(self, *, memory_id, data, metadata=None) -> MemoryRecord:
        return BaseMemoryProvider.update_memory(self, memory_id=memory_id, data=data, metadata=metadata)

    def delete_memory(self, *, memory_id) -> DeleteResult:
        return BaseMemoryProvider.delete_memory(self, memory_id=memory_id)


class InMemoryContractProviderHarnessTests(ProviderContractHarness, unittest.TestCase):
    def create_provider(self, runtime_dir: str):
        return InMemoryContractProvider(
            runtime_config={"runtime_dir": runtime_dir},
            provider_config=InMemoryContractProvider.default_provider_config(runtime_dir=runtime_dir),
        )

    def test_provider_specific_filter_support_is_exercised(self) -> None:
        self.create_memory("docs note", metadata={"topic": "docs"})
        self.create_memory("ops note", metadata={"topic": "ops"})

        records = self.provider.list_memories(**self.default_scope(), filters={"topic": "docs"})

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["metadata"]["topic"], "docs")


class ReadOnlyContractProviderHarnessTests(ProviderContractHarness, unittest.TestCase):
    def create_provider(self, runtime_dir: str):
        return ReadOnlyContractProvider(
            runtime_config={"runtime_dir": runtime_dir},
            provider_config=ReadOnlyContractProvider.default_provider_config(runtime_dir=runtime_dir),
        )
