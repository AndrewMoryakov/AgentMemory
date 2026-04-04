from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from memory_provider import BaseMemoryProvider


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalJsonProvider(BaseMemoryProvider):
    provider_name = "localjson"
    display_name = "Local JSON"

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

    def _public_record(self, record: dict[str, Any]) -> dict[str, Any]:
        return dict(record)

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

    def add_memory(self, *, messages, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None):
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

    def search_memory(self, *, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True):
        del rerank
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

    def list_memories(self, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None):
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
        raise KeyError(memory_id)

    def update_memory(self, *, memory_id, data, metadata=None):
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
        raise KeyError(memory_id)

    def delete_memory(self, *, memory_id):
        with self._lock:
            records = self._load_all()
            remaining = [record for record in records if record.get("id") != memory_id]
            if len(remaining) == len(records):
                raise KeyError(memory_id)
            self._save_all(remaining)
        return {"id": memory_id, "deleted": True}
