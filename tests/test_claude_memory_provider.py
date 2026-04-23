from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentmemory.providers.claude_memory import ClaudeMemoryProvider
from tests.provider_contract_harness import ProviderContractHarness


class ClaudeMemoryProviderHarnessTests(ProviderContractHarness, unittest.TestCase):
    def create_provider(self, runtime_dir: str):
        project_root = Path(runtime_dir) / "project"
        project_root.mkdir(parents=True, exist_ok=True)
        (project_root / ".git").mkdir(exist_ok=True)
        provider_config = ClaudeMemoryProvider.default_provider_config(runtime_dir=runtime_dir)
        provider_config.update(
            {
                "project_root": str(project_root),
                "user_claude_dir": str(Path(runtime_dir) / "user-claude"),
                "auto_memory_dir": str(Path(runtime_dir) / "auto-memory"),
                "include_user_memory": False,
                "include_auto_memory": False,
                "agentmemory_write_dir": str(project_root / ".claude" / "rules" / "agentmemory"),
            }
        )
        return ClaudeMemoryProvider(
            runtime_config={"runtime_dir": runtime_dir},
            provider_config=provider_config,
        )

    def test_claude_memory_capabilities_match_expected_behavior(self) -> None:
        capabilities = self.provider.capabilities()

        self.assertFalse(capabilities["supports_semantic_search"])
        self.assertTrue(capabilities["supports_text_search"])
        self.assertFalse(capabilities["supports_update"])
        self.assertFalse(capabilities["supports_delete"])
        self.assertFalse(capabilities["supports_scope_inventory"])


class ClaudeMemoryProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.project_root = self.base / "project"
        self.project_root.mkdir(parents=True, exist_ok=True)
        (self.project_root / ".git").mkdir(exist_ok=True)
        self.start_dir = self.project_root / "apps" / "api"
        self.start_dir.mkdir(parents=True, exist_ok=True)
        self.user_claude_dir = self.base / "user-claude"
        self.auto_memory_dir = self.base / "auto-memory"
        self.provider = ClaudeMemoryProvider(
            runtime_config={"runtime_dir": self.temp_dir.name},
            provider_config={
                **ClaudeMemoryProvider.default_provider_config(runtime_dir=self.temp_dir.name),
                "project_root": str(self.start_dir),
                "user_claude_dir": str(self.user_claude_dir),
                "auto_memory_dir": str(self.auto_memory_dir),
                "include_user_memory": True,
                "include_auto_memory": True,
                "agentmemory_write_dir": str(self.project_root / ".claude" / "rules" / "agentmemory"),
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write(self, path: Path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def test_list_memories_discovers_all_supported_surfaces(self) -> None:
        self._write(self.project_root / "CLAUDE.md", "# Project Root\n\nUse rye.\n")
        self._write(self.project_root / "apps" / "CLAUDE.local.md", "# App Notes\n\nUse uvicorn.\n")
        self._write(self.project_root / ".claude" / "CLAUDE.md", "# Shared Claude\n\nProject conventions.\n")
        self._write(self.project_root / ".claude" / "rules" / "style.md", "# Style\n\nPrefer typed Python.\n")
        self._write(self.user_claude_dir / "CLAUDE.md", "# User Memory\n\nAlways explain tradeoffs.\n")
        self._write(self.user_claude_dir / "rules" / "personal.md", "# Personal Rules\n\nPrefer concise answers.\n")
        self._write(self.auto_memory_dir / "MEMORY.md", "# Memory Index\n\nRemember build commands.\n")
        self._write(self.auto_memory_dir / "debugging.md", "# Debugging\n\nRedis must be local.\n")

        records = self.provider.list_memories(limit=20)
        source_paths = {record["metadata"]["source_path"] for record in records}
        info = self.provider.runtime_info()

        self.assertIn(str((self.project_root / "CLAUDE.md").resolve()), source_paths)
        self.assertIn(str((self.project_root / "apps" / "CLAUDE.local.md").resolve()), source_paths)
        self.assertIn(str((self.project_root / ".claude" / "CLAUDE.md").resolve()), source_paths)
        self.assertIn(str((self.project_root / ".claude" / "rules" / "style.md").resolve()), source_paths)
        self.assertIn(str((self.user_claude_dir / "CLAUDE.md").resolve()), source_paths)
        self.assertIn(str((self.user_claude_dir / "rules" / "personal.md").resolve()), source_paths)
        self.assertIn(str((self.auto_memory_dir / "MEMORY.md").resolve()), source_paths)
        self.assertIn(str((self.auto_memory_dir / "debugging.md").resolve()), source_paths)
        self.assertEqual(info["source_counts"]["project_walkup"], 2)
        self.assertEqual(info["source_counts"]["project_dot_claude"], 1)
        self.assertEqual(info["source_counts"]["project_rules"], 1)
        self.assertEqual(info["source_counts"]["user_memory"], 1)
        self.assertEqual(info["source_counts"]["user_rules"], 1)
        self.assertEqual(info["source_counts"]["auto_memory"], 2)

    def test_section_parsing_creates_stable_records_and_whole_file_fallback(self) -> None:
        self._write(
            self.project_root / "CLAUDE.md",
            "# Root\n\nBase rules.\n\n## Testing\n\nRun pytest.\n",
        )
        self._write(self.project_root / ".claude" / "rules" / "whole-file.md", "No headings here.\nUse black.\n")

        first = self.provider.list_memories(limit=20)
        second = self.provider.list_memories(limit=20)

        ids_first = {record["id"] for record in first}
        ids_second = {record["id"] for record in second}
        testing = next(record for record in first if record["metadata"].get("heading_path") == "Root / Testing")
        fallback = next(record for record in first if record["metadata"]["source_path"].endswith("whole-file.md"))

        self.assertEqual(ids_first, ids_second)
        self.assertIn("Run pytest.", testing["memory"])
        self.assertIsNone(fallback["metadata"].get("heading_path"))
        self.assertIn("No headings here.", fallback["memory"])

    def test_add_memory_writes_only_to_agentmemory_owned_directory(self) -> None:
        root_file = self.project_root / "CLAUDE.md"
        original = "# Root\n\nExisting user-authored memory.\n"
        self._write(root_file, original)

        created = self.provider.add_memory(
            messages=[{"role": "user", "content": "Prefer pnpm for workspace installs."}],
            user_id="u1",
            metadata={"topic": "tooling"},
        )

        write_dir = self.project_root / ".claude" / "rules" / "agentmemory"
        created_files = list(write_dir.glob("*.md"))
        fetched = self.provider.get_memory(created["id"])

        self.assertEqual(root_file.read_text(encoding="utf-8"), original)
        self.assertEqual(len(created_files), 1)
        self.assertEqual(created["id"], fetched["id"])
        self.assertEqual(created["user_id"], "u1")
        self.assertEqual(created["metadata"]["topic"], "tooling")
        self.assertFalse(created["metadata"]["read_only"])
        self.assertIn("Prefer pnpm", created["memory"])

    def test_search_uses_text_matching_across_claude_sources(self) -> None:
        self._write(self.project_root / "CLAUDE.md", "# Root\n\nUse rye for Python tasks.\n")
        self._write(self.auto_memory_dir / "debugging.md", "# Debugging\n\nRedis must be local for tests.\n")

        results = self.provider.search_memory(query="redis local", limit=10, rerank=False)

        self.assertEqual(len(results), 1)
        self.assertIn("Redis must be local", results[0]["memory"])
        self.assertGreaterEqual(results[0]["score"], 1.0)

    def test_list_scopes_returns_empty_canonical_shape(self) -> None:
        inventory = self.provider.list_scopes()
        page = self.provider.list_scopes_page(limit=1)

        self.assertEqual(inventory["provider"], "claude_memory")
        self.assertEqual(inventory["items"], [])
        self.assertEqual(inventory["totals"], {"users": 0, "agents": 0, "runs": 0})
        self.assertEqual(page["items"], [])
        self.assertEqual(page["totals"], {"users": 0, "agents": 0, "runs": 0})
        self.assertFalse(page["pagination_supported"])


if __name__ == "__main__":
    unittest.main()
