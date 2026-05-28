from __future__ import annotations

from datetime import datetime, timezone
import os
import sqlite3
from uuid import uuid4
import unittest
from unittest import mock

from agentmemory.providers.mem0 import Mem0Provider
from agentmemory.providers.base import MemoryNotFoundError, ProviderScopeRequiredError
from agentmemory.runtime import scope_registry
try:
    from provider_contract_harness import ProviderContractHarness
except ModuleNotFoundError:  # pragma: no cover
    from tests.provider_contract_harness import ProviderContractHarness


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FakeMem0Backend:
    def __init__(self) -> None:
        self._records: list[dict[str, object]] = []

    def _require_scope(self, *, user_id=None, agent_id=None, run_id=None) -> None:
        if user_id is None and agent_id is None and run_id is None:
            raise RuntimeError("At least one of 'user_id', 'agent_id', or 'run_id' must be provided.")

    def _match_scope(self, record: dict[str, object], *, user_id=None, agent_id=None, run_id=None) -> bool:
        if user_id is not None and record.get("user_id") != user_id:
            return False
        if agent_id is not None and record.get("agent_id") != agent_id:
            return False
        if run_id is not None and record.get("run_id") != run_id:
            return False
        return True

    def _match_filters(self, record: dict[str, object], filters: dict[str, object] | None) -> bool:
        if not filters:
            return True
        metadata = record.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        for key, expected in filters.items():
            actual = record.get(key, metadata.get(key))
            if actual != expected:
                return False
        return True

    def add(self, messages, *, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None):
        self._require_scope(user_id=user_id, agent_id=agent_id, run_id=run_id)
        parts = [str(item.get("content", "")) for item in messages if isinstance(item, dict) and item.get("content")]
        now = utc_now()
        record = {
            "id": str(uuid4()),
            "text": "\n".join(parts).strip(),
            "metadata": dict(metadata or {}),
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "memory_type": memory_type,
            "created_at": now,
            "updated_at": now,
            "category": "fake-mem0",
        }
        self._records.append(record)
        return dict(record)

    def search(self, query, *, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True):
        self._require_scope(user_id=user_id, agent_id=agent_id, run_id=run_id)
        query_l = query.lower()
        results: list[dict[str, object]] = []
        for record in self._records:
            if not self._match_scope(record, user_id=user_id, agent_id=agent_id, run_id=run_id):
                continue
            if not self._match_filters(record, filters):
                continue
            text = str(record.get("text", "")).lower()
            if query_l not in text:
                continue
            item = dict(record)
            item["score"] = 1.0 if rerank else 0.75
            if threshold is not None and float(item["score"]) < threshold:
                continue
            results.append(item)
        return {"results": results[:limit]}

    def get_all(self, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None):
        self._require_scope(user_id=user_id, agent_id=agent_id, run_id=run_id)
        records = [
            dict(record)
            for record in self._records
            if self._match_scope(record, user_id=user_id, agent_id=agent_id, run_id=run_id)
            and self._match_filters(record, filters)
        ]
        records.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return {"results": records[:limit]}

    def get(self, memory_id):
        for record in self._records:
            if record.get("id") == memory_id:
                return dict(record)
        raise MemoryNotFoundError(str(memory_id))

    def update(self, memory_id, data, *, metadata=None):
        for record in self._records:
            if record.get("id") == memory_id:
                record["text"] = data
                if metadata is not None:
                    record["metadata"] = dict(metadata)
                record["updated_at"] = utc_now()
                return dict(record)
        raise MemoryNotFoundError(str(memory_id))

    def delete(self, memory_id):
        for index, record in enumerate(self._records):
            if record.get("id") == memory_id:
                deleted_id = str(record["id"])
                del self._records[index]
                return {"id": deleted_id, "deleted": True}
        raise MemoryNotFoundError(str(memory_id))


class FakeMem0EmptyAddResultBackend(FakeMem0Backend):
    def add(self, messages, *, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None):
        record = super().add(
            messages,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            metadata=metadata,
            infer=infer,
            memory_type=memory_type,
        )
        return {"results": [], "raw_saved_record_id": record["id"]}


class FakeMem0NoIdAddResultBackend(FakeMem0Backend):
    """Persists the write but returns an add() result with no usable id or
    record, forcing the get_all-based fallback to attribute the just-added
    write among any pre-existing rows in the same scope."""

    def add(self, messages, *, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None):
        super().add(
            messages,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            metadata=metadata,
            infer=infer,
            memory_type=memory_type,
        )
        return {"results": []}


class FakeMem0MessageResultBackend(FakeMem0Backend):
    def update(self, memory_id, data, *, metadata=None):
        super().update(memory_id, data, metadata=metadata)
        return {"message": "Memory updated successfully!"}

    def delete(self, memory_id):
        super().delete(memory_id)
        return {"message": "Memory deleted successfully!"}


class FakeMem0MinimalAddWrapperBackend(FakeMem0Backend):
    def add(self, messages, *, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None):
        record = super().add(
            messages,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            metadata=metadata,
            infer=infer,
            memory_type=memory_type,
        )
        return {"results": [{"id": record["id"], "memory": record["text"], "event": "ADD"}]}


class FakeMem0FanoutAddBackend(FakeMem0Backend):
    """Simulates mem0 with infer=true splitting one input into three extracted
    facts — each becomes its own ADD event in the results envelope."""

    def add(self, messages, *, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None):
        self._require_scope(user_id=user_id, agent_id=agent_id, run_id=run_id)
        now = utc_now()
        facts = [
            "First extracted fact",
            "Second extracted fact",
            "Third extracted fact",
        ]
        results = []
        for text in facts:
            record = {
                "id": str(uuid4()),
                "text": text,
                "metadata": dict(metadata or {}),
                "user_id": user_id,
                "agent_id": agent_id,
                "run_id": run_id,
                "memory_type": memory_type,
                "created_at": now,
                "updated_at": now,
                "category": "fake-mem0",
            }
            self._records.append(record)
            results.append({"id": record["id"], "memory": record["text"], "event": "ADD"})
        return {"results": results}


class FakeMem0PartialScopeAddBackend(FakeMem0Backend):
    def add(self, messages, *, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None):
        record = super().add(
            messages,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            metadata=metadata,
            infer=infer,
            memory_type=memory_type,
        )
        return {"results": [{"id": record["id"], "memory": record["text"], "event": "ADD"}]}

    def get(self, memory_id):
        raise MemoryNotFoundError(str(memory_id))


class FakeMem0SemanticBackend(FakeMem0Backend):
    def search(self, query, *, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True):
        self._require_scope(user_id=user_id, agent_id=agent_id, run_id=run_id)
        results: list[dict[str, object]] = []
        for record in self._records:
            if not self._match_scope(record, user_id=user_id, agent_id=agent_id, run_id=run_id):
                continue
            if not self._match_filters(record, filters):
                continue
            item = dict(record)
            item["score"] = 0.92 if rerank else 0.81
            if threshold is not None and float(item["score"]) < threshold:
                continue
            results.append(item)
        return {"results": results[:limit]}


class HarnessMem0Provider(Mem0Provider):
    def __init__(self, *, runtime_config: dict[str, object], provider_config: dict[str, object]) -> None:
        super().__init__(runtime_config=runtime_config, provider_config=provider_config)
        self._fake_memory = FakeMem0Backend()

    def _load_memory(self):  # type: ignore[override]
        return self._fake_memory

    def _iter_scope_payloads(self):  # type: ignore[override]
        return [dict(record) for record in self._fake_memory._records]


class EmptyAddResultMem0Provider(HarnessMem0Provider):
    def __init__(self, *, runtime_config: dict[str, object], provider_config: dict[str, object]) -> None:
        Mem0Provider.__init__(self, runtime_config=runtime_config, provider_config=provider_config)
        self._fake_memory = FakeMem0EmptyAddResultBackend()


class NoIdAddResultMem0Provider(HarnessMem0Provider):
    def __init__(self, *, runtime_config: dict[str, object], provider_config: dict[str, object]) -> None:
        Mem0Provider.__init__(self, runtime_config=runtime_config, provider_config=provider_config)
        self._fake_memory = FakeMem0NoIdAddResultBackend()


class MessageResultMem0Provider(HarnessMem0Provider):
    def __init__(self, *, runtime_config: dict[str, object], provider_config: dict[str, object]) -> None:
        Mem0Provider.__init__(self, runtime_config=runtime_config, provider_config=provider_config)
        self._fake_memory = FakeMem0MessageResultBackend()


class MinimalAddWrapperMem0Provider(HarnessMem0Provider):
    def __init__(self, *, runtime_config: dict[str, object], provider_config: dict[str, object]) -> None:
        Mem0Provider.__init__(self, runtime_config=runtime_config, provider_config=provider_config)
        self._fake_memory = FakeMem0MinimalAddWrapperBackend()


class SemanticMem0Provider(HarnessMem0Provider):
    def __init__(self, *, runtime_config: dict[str, object], provider_config: dict[str, object]) -> None:
        Mem0Provider.__init__(self, runtime_config=runtime_config, provider_config=provider_config)
        self._fake_memory = FakeMem0SemanticBackend()


class FanoutAddMem0Provider(HarnessMem0Provider):
    def __init__(self, *, runtime_config: dict[str, object], provider_config: dict[str, object]) -> None:
        Mem0Provider.__init__(self, runtime_config=runtime_config, provider_config=provider_config)
        self._fake_memory = FakeMem0FanoutAddBackend()


class PartialScopeAddMem0Provider(HarnessMem0Provider):
    def __init__(self, *, runtime_config: dict[str, object], provider_config: dict[str, object]) -> None:
        Mem0Provider.__init__(self, runtime_config=runtime_config, provider_config=provider_config)
        self._fake_memory = FakeMem0PartialScopeAddBackend()


class Mem0ProviderHarnessTests(ProviderContractHarness, unittest.TestCase):
    def create_provider(self, runtime_dir: str):
        return HarnessMem0Provider(
            runtime_config={"runtime_dir": runtime_dir},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=runtime_dir),
        )

    def test_mem0_capabilities_match_expected_behavior(self) -> None:
        capabilities = self.provider.capabilities()

        self.assertTrue(capabilities["supports_semantic_search"])
        self.assertTrue(capabilities["supports_rerank"])
        self.assertTrue(capabilities["requires_scope_for_search"])
        self.assertTrue(capabilities["supports_owner_process_mode"])

    def test_load_memory_passes_api_key_in_config_without_mutating_process_env(self) -> None:
        original_env = {
            "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY"),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
            "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL"),
        }
        captured_config: dict[str, object] = {}
        leaked_openai_api_key = None
        leaked_openai_base_url = None
        provider = Mem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )
        try:
            os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-test"
            os.environ.pop("OPENAI_API_KEY", None)
            os.environ.pop("OPENAI_BASE_URL", None)

            def fake_from_config(config):
                captured_config.update(config)
                return object()

            with mock.patch("agentmemory.providers.mem0._install_openai_usage_capture", lambda: None), \
                 mock.patch("agentmemory.providers.mem0.Memory.from_config", side_effect=fake_from_config):
                provider._load_memory()
            leaked_openai_api_key = os.environ.get("OPENAI_API_KEY")
            leaked_openai_base_url = os.environ.get("OPENAI_BASE_URL")
        finally:
            provider.clear_caches()
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        llm_config = captured_config["llm"]["config"]  # type: ignore[index]
        embedder_config = captured_config["embedder"]["config"]  # type: ignore[index]
        self.assertEqual(llm_config["api_key"], "sk-or-v1-test")
        self.assertEqual(embedder_config["api_key"], "sk-or-v1-test")
        self.assertIsNone(leaked_openai_api_key)
        self.assertIsNone(leaked_openai_base_url)

    def test_mem0_search_requires_scope(self) -> None:
        with self.assertRaises(ProviderScopeRequiredError):
            self.provider.search_memory(query="demo")

    def test_mem0_list_honors_metadata_filters(self) -> None:
        self.create_memory("docs note", metadata={"topic": "docs"})
        self.create_memory("ops note", metadata={"topic": "ops"})

        records = self.provider.list_memories(**self.default_scope(), filters={"topic": "docs"})

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["metadata"]["topic"], "docs")

    def test_add_falls_back_when_mem0_returns_empty_results_wrapper(self) -> None:
        provider = EmptyAddResultMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )

        created = provider.add_memory(
            messages=[{"role": "user", "content": "ssh host is 185.177.219.147"}],
            user_id="default",
            metadata={"topic": "ops"},
        )

        self.assertEqual(created["memory"], "ssh host is 185.177.219.147")
        self.assertEqual(created["metadata"]["topic"], "ops")
        self.assertEqual(created["provider"], "mem0")

    def test_add_fallback_does_not_return_preexisting_record_without_id(self) -> None:
        provider = NoIdAddResultMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )
        existing = provider.add_memory(
            messages=[{"role": "user", "content": "pre-existing note"}],
            user_id="default",
        )

        created = provider.add_memory(
            messages=[{"role": "user", "content": "brand new note"}],
            user_id="default",
        )

        # The fallback must attribute the just-added write by its text, never
        # borrow the pre-existing row that get_all happens to list first.
        self.assertEqual(created["memory"], "brand new note")
        self.assertNotEqual(created["id"], existing["id"])

    def test_update_uses_get_fallback_for_message_only_success_response(self) -> None:
        provider = MessageResultMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )
        created = provider.add_memory(messages=[{"role": "user", "content": "old text"}], user_id="default")

        updated = provider.update_memory(memory_id=created["id"], data="new text", metadata={"v": 2})

        self.assertEqual(updated["id"], created["id"])
        self.assertEqual(updated["memory"], "new text")
        self.assertEqual(updated["metadata"]["v"], 2)

    def test_add_hydrates_minimal_event_wrapper_response(self) -> None:
        provider = MinimalAddWrapperMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )

        created = provider.add_memory(
            messages=[{"role": "user", "content": "server host note"}],
            user_id="default",
            metadata={"topic": "ops"},
        )

        self.assertEqual(created["memory"], "server host note")
        self.assertEqual(created["user_id"], "default")
        self.assertEqual(created["metadata"]["topic"], "ops")

    def test_delete_accepts_message_only_success_response(self) -> None:
        provider = MessageResultMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )
        created = provider.add_memory(messages=[{"role": "user", "content": "temporary"}], user_id="default")

        deleted = provider.delete_memory(memory_id=created["id"])

        self.assertTrue(deleted["deleted"])
        self.assertEqual(deleted["id"], created["id"])

    def test_add_surfaces_fanout_records_and_syncs_each_to_scope_registry(self) -> None:
        provider = FanoutAddMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )

        created = provider.add_memory(
            messages=[{"role": "user", "content": "a paragraph that mem0 splits into three facts"}],
            user_id="default",
        )

        # The returned record is the first fan-out result; the remainder are
        # exposed verbatim under additional_records so the caller can see them.
        self.assertEqual(created["memory"], "First extracted fact")
        additional = created.get("additional_records")
        self.assertIsInstance(additional, list)
        self.assertEqual(len(additional), 2)
        self.assertEqual([r["memory"] for r in additional], ["Second extracted fact", "Third extracted fact"])
        all_ids = {created["id"], *(r["id"] for r in additional)}
        self.assertEqual(len(all_ids), 3, "every fan-out record must carry its own id")

        # Every produced id must reach the scope registry — list_scopes must
        # see all three rather than just the primary.
        inventory = provider.list_scopes()
        users_entry = next((item for item in inventory["items"] if item["kind"] == "user" and item["value"] == "default"), None)
        self.assertIsNotNone(users_entry)
        self.assertEqual(users_entry["count"], 3)

    def test_add_omits_additional_records_when_only_one_returned(self) -> None:
        # Confirms we don't add the field when mem0 produces a single ADD —
        # callers can rely on its presence as a real signal.
        provider = HarnessMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )

        created = provider.add_memory(messages=[{"role": "user", "content": "one fact"}], user_id="default")

        self.assertNotIn("additional_records", created)

    def test_get_memory_raises_not_found_for_each_empty_sentinel(self) -> None:
        # Real mem0 sometimes returns None / {} / {"results": []} when an id
        # does not exist instead of raising. Each shape must still surface
        # as MemoryNotFoundError so HTTP/MCP callers get a 404, never the
        # generic 400 the old normalize path produced.
        for sentinel in (None, {}, {"results": []}, []):
            with self.subTest(sentinel=sentinel):
                with mock.patch.object(self.provider._fake_memory, "get", return_value=sentinel):
                    with self.assertRaises(MemoryNotFoundError):
                        self.provider.get_memory("does-not-exist")

    def test_get_memory_still_surfaces_validation_error_for_malformed_payload(self) -> None:
        # A non-empty dict that lacks an id is genuinely malformed — that's
        # a provider-side data integrity error, not a "not found", so it
        # must keep raising ProviderValidationError, never collapse to 404.
        with mock.patch.object(self.provider._fake_memory, "get", return_value={"memory": "no id here"}):
            with self.assertRaises(Exception) as ctx:
                self.provider.get_memory("any-id")
        self.assertNotIsInstance(ctx.exception, MemoryNotFoundError)

    def test_update_memory_raises_not_found_when_followup_get_is_empty(self) -> None:
        # mem0 may answer update() with just "Memory updated successfully!"
        # In that case the provider re-fetches by id to build the response.
        # If the re-fetch comes back empty, surface NotFound — not a generic
        # validation error from _normalize_one_record.
        provider = MessageResultMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )
        created = provider.add_memory(messages=[{"role": "user", "content": "x"}], user_id="default")
        with mock.patch.object(provider._fake_memory, "get", return_value=None):
            with self.assertRaises(MemoryNotFoundError):
                provider.update_memory(memory_id=created["id"], data="y")

    def test_partial_add_result_skips_registry_and_marks_needs_rebuild(self) -> None:
        provider = PartialScopeAddMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )

        created = provider.add_memory(
            messages=[{"role": "user", "content": "server host note"}],
            user_id="default",
            metadata={"topic": "ops"},
        )
        inventory = provider.list_scopes()
        status = scope_registry.scope_registry_status(provider.provider_name, provider.runtime_dir)

        self.assertEqual(created["memory"], "server host note")
        self.assertEqual(inventory["totals"], {"users": 0, "agents": 0, "runs": 0})
        self.assertEqual(status["status"], "needs_rebuild")
        self.assertEqual(status["last_failed_operation"], "add")

    def test_mem0_add_returns_success_when_registry_sync_fails(self) -> None:
        provider = HarnessMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )

        with mock.patch("agentmemory.providers.mem0.scope_registry.upsert_record", side_effect=sqlite3.OperationalError("boom")):
            created = provider.add_memory(messages=[{"role": "user", "content": "note"}], user_id="default")

        records = provider.list_memories(user_id="default")
        status = scope_registry.scope_registry_status(provider.provider_name, provider.runtime_dir)

        self.assertEqual(created["memory"], "note")
        self.assertEqual(len(records), 1)
        self.assertEqual(status["status"], "needs_rebuild")
        self.assertEqual(status["last_failed_operation"], "add")

    def test_mem0_update_returns_success_when_registry_sync_fails(self) -> None:
        provider = HarnessMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )
        created = provider.add_memory(messages=[{"role": "user", "content": "old"}], user_id="default")

        with mock.patch("agentmemory.providers.mem0.scope_registry.upsert_record", side_effect=sqlite3.OperationalError("boom")):
            updated = provider.update_memory(memory_id=created["id"], data="new", metadata={"v": 2})

        fetched = provider.get_memory(created["id"])
        status = scope_registry.scope_registry_status(provider.provider_name, provider.runtime_dir)

        self.assertEqual(updated["memory"], "new")
        self.assertEqual(fetched["memory"], "new")
        self.assertEqual(status["status"], "needs_rebuild")
        self.assertEqual(status["last_failed_operation"], "update")

    def test_mem0_delete_returns_success_when_registry_sync_fails(self) -> None:
        provider = HarnessMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )
        created = provider.add_memory(messages=[{"role": "user", "content": "old"}], user_id="default")

        with mock.patch("agentmemory.providers.mem0.scope_registry.delete_record", side_effect=sqlite3.OperationalError("boom")):
            deleted = provider.delete_memory(memory_id=created["id"])

        status = scope_registry.scope_registry_status(provider.provider_name, provider.runtime_dir)

        self.assertTrue(deleted["deleted"])
        self.assertEqual(provider.list_memories(user_id="default"), [])
        self.assertEqual(status["status"], "needs_rebuild")
        self.assertEqual(status["last_failed_operation"], "delete")

    def test_successful_sync_clears_registry_degraded_state(self) -> None:
        provider = HarnessMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )
        scope_registry.mark_sync_failed(
            provider.provider_name,
            provider.runtime_dir,
            operation="add",
            memory_id="missing",
            error=sqlite3.OperationalError("boom"),
        )

        provider.add_memory(messages=[{"role": "user", "content": "ok"}], user_id="default")
        status = scope_registry.scope_registry_status(provider.provider_name, provider.runtime_dir)

        self.assertEqual(status["status"], "ok")

    def test_mem0_search_preserves_semantic_scores_and_threshold(self) -> None:
        provider = SemanticMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )
        provider.add_memory(
            messages=[{"role": "user", "content": "deploy target is local machine"}],
            user_id="default",
            metadata={"topic": "ops"},
        )

        results = provider.search_memory(query="server host", user_id="default", threshold=0.9, rerank=True)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["memory"], "deploy target is local machine")
        self.assertAlmostEqual(results[0]["score"], 0.92, places=2)

    def test_mem0_search_keeps_scope_isolation_in_semantic_mode(self) -> None:
        provider = SemanticMem0Provider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=Mem0Provider.default_provider_config(runtime_dir=self.temp_dir.name),
        )
        provider.add_memory(messages=[{"role": "user", "content": "server note"}], user_id="default")
        provider.add_memory(messages=[{"role": "user", "content": "other tenant note"}], user_id="other-user")

        results = provider.search_memory(query="machine host", user_id="default", rerank=False)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["user_id"], "default")
        self.assertAlmostEqual(results[0]["score"], 0.81, places=2)


if __name__ == "__main__":
    unittest.main()
