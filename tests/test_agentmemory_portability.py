import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agentmemory.runtime.portability as portability
from agentmemory.providers.base import ProviderValidationError


class AgentMemoryPortabilityTests(unittest.TestCase):
    def test_export_memories_writes_provider_neutral_jsonl_with_dedup(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        export_path = Path(temp_dir.name) / "memories.jsonl"
        try:
            records_by_scope = {
                ("user_id", "u1"): [
                    {
                        "id": "m-1",
                        "memory": "prefers tea",
                        "metadata": {"topic": "drink"},
                        "user_id": "u1",
                        "provider": "mem0",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
                ("agent_id", "a1"): [
                    {
                        "id": "m-1",
                        "memory": "prefers tea",
                        "metadata": {"topic": "drink"},
                        "user_id": "u1",
                        "agent_id": "a1",
                        "provider": "mem0",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    {
                        "id": "m-2",
                        "memory": "works on docs",
                        "metadata": {},
                        "agent_id": "a1",
                        "provider": "mem0",
                        "created_at": "2026-01-02T00:00:00Z",
                    },
                ],
                (None, None): [
                    {
                        "id": "m-2",
                        "memory": "works on docs",
                        "metadata": {},
                        "agent_id": "a1",
                        "provider": "mem0",
                        "created_at": "2026-01-02T00:00:00Z",
                    }
                ],
            }

            def fake_list(**kwargs):
                if "user_id" in kwargs and kwargs["user_id"]:
                    return records_by_scope[("user_id", kwargs["user_id"])]
                if "agent_id" in kwargs and kwargs["agent_id"]:
                    return records_by_scope[("agent_id", kwargs["agent_id"])]
                return records_by_scope[(None, None)]

            with (
                mock.patch.object(portability, "active_provider_name", return_value="mem0"),
                mock.patch.object(
                    portability,
                    "active_provider_capabilities",
                    return_value={"supports_scopeless_list": True},
                ),
                mock.patch.object(
                    portability,
                    "memory_list_scopes",
                    return_value={
                        "provider": "mem0",
                        "items": [
                            {"kind": "user", "value": "u1", "count": 1, "last_seen_at": None},
                            {"kind": "agent", "value": "a1", "count": 2, "last_seen_at": None},
                        ],
                        "totals": {"users": 1, "agents": 1, "runs": 0},
                    },
                ),
                mock.patch.object(portability, "memory_list", side_effect=fake_list),
            ):
                payload = portability.export_memories(path=str(export_path))
            lines = export_path.read_text(encoding="utf-8").splitlines()
        finally:
            temp_dir.cleanup()

        self.assertEqual(payload["provider"], "mem0")
        self.assertEqual(payload["exported"], 2)
        decoded = [json.loads(line) for line in lines]
        self.assertEqual([item["id"] for item in decoded], ["m-1", "m-2"])
        self.assertEqual(decoded[0]["metadata"], {"topic": "drink"})
        self.assertEqual(decoded[1]["provider"], "mem0")

    def test_export_memories_uses_pagination_for_paginated_provider(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        export_path = Path(temp_dir.name) / "memories.jsonl"
        records = [
            {
                "id": f"m-{idx}",
                "memory": f"note {idx}",
                "metadata": {},
                "user_id": "u1",
                "provider": "localjson",
                "created_at": f"2026-01-0{idx + 1}T00:00:00Z",
            }
            for idx in range(3)
        ]
        try:
            def fake_list_page(**kwargs):
                cursor = int(kwargs.get("cursor") or 0)
                limit = int(kwargs.get("limit") or 2)
                page = records[cursor : cursor + limit]
                next_cursor = cursor + len(page)
                return {
                    "provider": "localjson",
                    "items": page,
                    "next_cursor": str(next_cursor) if next_cursor < len(records) else None,
                    "pagination_supported": True,
                }

            with (
                mock.patch.object(portability, "active_provider_name", return_value="localjson"),
                mock.patch.object(
                    portability,
                    "active_provider_capabilities",
                    return_value={"supports_scopeless_list": True, "supports_pagination": True},
                ),
                mock.patch.object(
                    portability,
                    "memory_list_scopes",
                    return_value={"provider": "localjson", "items": [], "totals": {"users": 0, "agents": 0, "runs": 0}},
                ),
                mock.patch.object(portability, "EXPORT_PAGE_SIZE", 2),
                mock.patch.object(portability, "memory_list_page", side_effect=fake_list_page),
            ):
                payload = portability.export_memories(path=str(export_path))
            decoded = [json.loads(line) for line in export_path.read_text(encoding="utf-8").splitlines()]
        finally:
            temp_dir.cleanup()

        self.assertTrue(payload["pagination_used"])
        self.assertEqual(payload["exported"], 3)
        self.assertEqual([item["id"] for item in decoded], ["m-0", "m-1", "m-2"])

    def test_export_memories_rejects_possible_scope_truncation(self) -> None:
        with (
            mock.patch.object(portability, "active_provider_name", return_value="mem0"),
            mock.patch.object(
                portability,
                "active_provider_capabilities",
                return_value={"supports_scopeless_list": False},
            ),
            mock.patch.object(
                portability,
                "memory_list_scopes",
                return_value={
                    "provider": "mem0",
                    "items": [{}] * portability.EXPORT_SCOPE_LIMIT,
                    "totals": {"users": portability.EXPORT_SCOPE_LIMIT, "agents": 0, "runs": 0},
                },
            ),
        ):
            with self.assertRaises(ProviderValidationError):
                portability.export_memories(path="memories.jsonl")

    def test_import_memories_replays_records_with_provenance_and_infer_false(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        import_path = Path(temp_dir.name) / "memories.jsonl"
        import_path.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "id": "m-1",
                            "memory": "prefers tea",
                            "metadata": {"topic": "drink", "source": "user"},
                            "user_id": "u1",
                            "provider": "mem0",
                            "created_at": "2026-01-01T00:00:00Z",
                        },
                        ensure_ascii=True,
                    ),
                    json.dumps(
                        {
                            "id": "m-2",
                            "memory": "works on docs",
                            "metadata": {},
                            "agent_id": "a1",
                            "provider": "localjson",
                        },
                        ensure_ascii=True,
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        captured: list[dict[str, object]] = []
        try:
            with (
                mock.patch.object(portability, "active_provider_name", return_value="localjson"),
                mock.patch.object(
                    portability,
                    "memory_add",
                    side_effect=lambda **kwargs: captured.append(kwargs) or {"id": f"new-{len(captured)}"},
                ),
            ):
                payload = portability.import_memories(path=str(import_path))
        finally:
            temp_dir.cleanup()

        self.assertEqual(payload["provider"], "localjson")
        self.assertEqual(payload["imported"], 2)
        self.assertFalse(captured[0]["infer"])
        self.assertEqual(captured[0]["messages"], [{"role": "user", "content": "prefers tea"}])
        self.assertEqual(captured[0]["metadata"]["source"], "import")
        self.assertEqual(captured[0]["metadata"]["import_original_source"], "user")
        self.assertEqual(captured[0]["metadata"]["import_provider"], "mem0")
        self.assertEqual(captured[1]["metadata"]["imported_memory_id"], "m-2")
