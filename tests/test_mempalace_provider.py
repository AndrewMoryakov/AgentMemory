from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentmemory.providers.base import MemoryNotFoundError, ProviderCapabilityError
from agentmemory.providers.mempalace import MemPalaceProvider
from tests.provider_contract_harness import ProviderContractHarness


class FakePalaceNotFoundError(RuntimeError):
    pass


class FakeBackendError(RuntimeError):
    pass


class FakeQueryResult:
    def __init__(self, *, ids, documents, metadatas, distances) -> None:
        self.ids = [ids]
        self.documents = [documents]
        self.metadatas = [metadatas]
        self.distances = [distances]
        self.embeddings = None


class FakeGetResult:
    def __init__(self, *, ids, documents, metadatas) -> None:
        self.ids = ids
        self.documents = documents
        self.metadatas = metadatas
        self.embeddings = None


def _matches_where(metadata: dict[str, object], where: dict[str, object] | None) -> bool:
    if not where:
        return True
    for key, expected in where.items():
        if metadata.get(key) != expected:
            return False
    return True


class FakeMemPalaceCollection:
    def __init__(self, store: dict[str, dict[str, object]]) -> None:
        self._store = store

    def add(self, *, documents, ids, metadatas=None, embeddings=None) -> None:
        del embeddings
        for index, memory_id in enumerate(ids):
            if memory_id in self._store:
                raise FakeBackendError(f"duplicate id: {memory_id}")
            self._store[str(memory_id)] = {
                "document": documents[index],
                "metadata": dict((metadatas or [{}])[index] or {}),
            }

    def query(self, *, query_texts=None, query_embeddings=None, n_results=10, where=None, where_document=None, include=None):
        del query_embeddings, where_document, include
        query = str((query_texts or [""])[0]).lower()
        matches: list[tuple[float, str, str, dict[str, object]]] = []
        for memory_id, payload in self._store.items():
            metadata = dict(payload["metadata"])
            if not _matches_where(metadata, where):
                continue
            document = str(payload["document"])
            document_lower = document.lower()
            if query and query in document_lower:
                distance = 0.0
            else:
                query_tokens = {token for token in query.split() if token}
                doc_tokens = {token for token in document_lower.split() if token}
                overlap = len(query_tokens & doc_tokens)
                distance = 0.7 if overlap else 1.8
            matches.append((distance, memory_id, document, metadata))
        matches.sort(key=lambda item: (item[0], item[1]))
        selected = matches[:n_results]
        return FakeQueryResult(
            ids=[item[1] for item in selected],
            documents=[item[2] for item in selected],
            metadatas=[item[3] for item in selected],
            distances=[item[0] for item in selected],
        )

    def get(self, *, ids=None, where=None, where_document=None, limit=None, offset=None, include=None):
        del where_document, include
        rows: list[tuple[str, str, dict[str, object]]] = []
        for memory_id, payload in self._store.items():
            if ids is not None and memory_id not in ids:
                continue
            metadata = dict(payload["metadata"])
            if not _matches_where(metadata, where):
                continue
            rows.append((memory_id, str(payload["document"]), metadata))
        rows.sort(key=lambda item: item[0])
        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return FakeGetResult(
            ids=[item[0] for item in rows],
            documents=[item[1] for item in rows],
            metadatas=[item[2] for item in rows],
        )

    def delete(self, *, ids=None, where=None) -> None:
        targets: list[str] = []
        for memory_id, payload in self._store.items():
            if ids is not None and memory_id not in ids:
                continue
            metadata = dict(payload["metadata"])
            if not _matches_where(metadata, where):
                continue
            targets.append(memory_id)
        for memory_id in targets:
            self._store.pop(memory_id, None)

    def count(self) -> int:
        return len(self._store)


class FakeMemPalaceApi:
    def __init__(self) -> None:
        self.version = "3.3.5"
        self.palace_not_found_error = FakePalaceNotFoundError
        self.backend_error = FakeBackendError
        self._collections: dict[tuple[str, str], dict[str, dict[str, object]]] = {}

    def get_collection(self, *, palace_path, collection_name=None, create=True):
        key = (str(Path(palace_path)), str(collection_name or "agentmemory_records"))
        if not create and key not in self._collections:
            raise FakePalaceNotFoundError(str(palace_path))
        store = self._collections.setdefault(key, {})
        return FakeMemPalaceCollection(store)

    def snapshot(self, palace_path: str, collection_name: str) -> dict[str, dict[str, object]]:
        return self._collections.get((str(Path(palace_path)), collection_name), {})


class _PatchedMemPalaceProviderCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.fake_api = FakeMemPalaceApi()
        self.loader_patch = mock.patch("agentmemory.providers.mempalace._load_mempalace_api", return_value=self.fake_api)
        self.loader_patch.start()

    def tearDown(self) -> None:
        self.loader_patch.stop()
        super().tearDown()


class MemPalaceProviderHarnessTests(ProviderContractHarness, _PatchedMemPalaceProviderCase):
    def setUp(self) -> None:
        _PatchedMemPalaceProviderCase.setUp(self)
        ProviderContractHarness.setUp(self)

    def tearDown(self) -> None:
        ProviderContractHarness.tearDown(self)
        _PatchedMemPalaceProviderCase.tearDown(self)

    def create_provider(self, runtime_dir: str):
        return MemPalaceProvider(
            runtime_config={"runtime_dir": runtime_dir},
            provider_config=MemPalaceProvider.default_provider_config(runtime_dir=runtime_dir),
        )


class MemPalaceProviderTests(_PatchedMemPalaceProviderCase):
    def setUp(self) -> None:
        super().setUp()
        self.temp_dir = tempfile.TemporaryDirectory()
        runtime_dir = self.temp_dir.name
        self.provider = MemPalaceProvider(
            runtime_config={"runtime_dir": runtime_dir},
            provider_config=MemPalaceProvider.default_provider_config(runtime_dir=runtime_dir),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        super().tearDown()

    def make_messages(self, text: str) -> list[dict[str, str]]:
        return [{"role": "user", "content": text}]

    def test_install_requirements_pin_provider_dependency(self) -> None:
        self.assertEqual(MemPalaceProvider.install_requirements(), ["mempalace==3.3.5"])

    def test_provider_persists_agentmemory_metadata_in_backend(self) -> None:
        created = self.provider.add_memory(
            messages=self.make_messages("project uses local runtime"),
            user_id="alice",
            agent_id="builder",
            run_id="run-1",
            metadata={"topic": "runtime"},
            memory_type="fact",
        )

        snapshot = self.fake_api.snapshot(str(self.provider.palace_path), self.provider.collection_name)
        payload = snapshot[created["id"]]
        backend_metadata = dict(payload["metadata"])

        self.assertTrue(backend_metadata["agentmemory_managed"])
        self.assertEqual(backend_metadata["palace_id"], "agentmemory")
        self.assertEqual(backend_metadata["user_id"], "alice")
        self.assertEqual(backend_metadata["agent_id"], "builder")
        self.assertEqual(backend_metadata["run_id"], "run-1")
        self.assertEqual(backend_metadata["memory_type"], "fact")
        self.assertIn('"topic": "runtime"', backend_metadata["agentmemory_metadata_json"])

    def test_list_and_search_apply_scope_filtering(self) -> None:
        self.provider.add_memory(messages=self.make_messages("shared note"), user_id="alice")
        self.provider.add_memory(messages=self.make_messages("shared note"), user_id="bob")

        listed = self.provider.list_memories(user_id="alice")
        searched = self.provider.search_memory(query="shared", user_id="bob", rerank=False)

        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["user_id"], "alice")
        self.assertEqual(len(searched), 1)
        self.assertEqual(searched[0]["user_id"], "bob")

    def test_delete_removes_scope_registry_row(self) -> None:
        created = self.provider.add_memory(messages=self.make_messages("delete me"), user_id="alice")
        before = self.provider.list_scopes()

        deleted = self.provider.delete_memory(memory_id=created["id"])
        after = self.provider.list_scopes()

        self.assertTrue(deleted["deleted"])
        self.assertEqual(before["totals"]["users"], 1)
        self.assertEqual(after["totals"]["users"], 0)

    def test_search_normalizes_score_and_applies_threshold(self) -> None:
        self.provider.add_memory(messages=self.make_messages("semantic brutalist layouts"), user_id="alice")

        results = self.provider.search_memory(query="brutalist", user_id="alice", rerank=False, threshold=1.5)

        self.assertEqual(len(results), 1)
        self.assertGreaterEqual(results[0]["score"], 1.5)

    def test_missing_palace_returns_empty_collections_and_not_found_for_record_ops(self) -> None:
        listed = self.provider.list_memories(user_id="alice")
        searched = self.provider.search_memory(query="missing", user_id="alice", rerank=False)

        self.assertEqual(listed, [])
        self.assertEqual(searched, [])
        with self.assertRaises(MemoryNotFoundError):
            self.provider.get_memory("missing")
        with self.assertRaises(MemoryNotFoundError):
            self.provider.delete_memory(memory_id="missing")

    def test_runtime_info_reports_record_count(self) -> None:
        self.provider.add_memory(messages=self.make_messages("first"), user_id="alice")
        self.provider.add_memory(messages=self.make_messages("second"), user_id="alice")

        payload = self.provider.runtime_info()

        self.assertTrue(payload["package_available"])
        self.assertEqual(payload["package_version"], "3.3.5")
        self.assertEqual(payload["record_count"], 2)

    def test_filters_are_rejected_in_phase_one(self) -> None:
        self.provider.add_memory(messages=self.make_messages("docs memory"), user_id="alice")

        with self.assertRaises(ProviderCapabilityError):
            self.provider.list_memories(user_id="alice", filters={"topic": "docs"})
        with self.assertRaises(ProviderCapabilityError):
            self.provider.search_memory(query="docs", user_id="alice", filters={"topic": "docs"}, rerank=False)

    def test_rebuild_seed_records_return_current_records(self) -> None:
        created = self.provider.add_memory(messages=self.make_messages("seed me"), user_id="alice")

        records = self.provider.iter_scope_registry_seed_records()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], created["id"])


class MemPalaceProviderDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.provider = MemPalaceProvider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config=MemPalaceProvider.default_provider_config(runtime_dir=self.temp_dir.name),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_dependency_checks_and_health_report_missing_package_cleanly(self) -> None:
        with mock.patch("agentmemory.providers.mempalace._load_mempalace_api", side_effect=ModuleNotFoundError("mempalace")):
            checks = self.provider.dependency_checks()
            runtime_info = self.provider.runtime_info()
            health = self.provider.health()

        self.assertEqual(checks[0]["name"], "mempalace")
        self.assertEqual(checks[0]["ok"], "false")
        self.assertFalse(runtime_info["package_available"])
        self.assertFalse(health["ok"])

    def test_provider_module_import_is_safe_without_mempalace_installed(self) -> None:
        with mock.patch("agentmemory.providers.mempalace._load_mempalace_api", side_effect=ModuleNotFoundError("mempalace")):
            self.assertFalse(self.provider.runtime_info()["package_available"])


if __name__ == "__main__":
    unittest.main()
