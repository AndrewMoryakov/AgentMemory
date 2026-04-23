from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentmemory.providers.base import (
    BaseMemoryProvider,
    MemoryNotFoundError,
    MemoryRecord,
    ProviderCapabilities,
    ProviderCapabilityError,
    ProviderContract,
    ProviderRuntimePolicy,
    ProviderValidationError,
    ScopeInventory,
)


_AGENTMEMORY_HEADER_PREFIX = "<!-- agentmemory-record: "
_AGENTMEMORY_HEADER_SUFFIX = " -->"
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _utc_iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _discover_git_root(path: Path) -> Path:
    current = path if path.is_dir() else path.parent
    current = current.expanduser().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def _normalize_claude_project_key(path: Path) -> str:
    return "".join(ch if ch.isalnum() or ch in {".", "_", "-"} else "-" for ch in str(path))


class ClaudeMemoryProvider(BaseMemoryProvider):
    provider_name = "claude_memory"
    display_name = "Claude Memory"
    summary = "Conservative file-backed adapter over Claude Code memory surfaces with safe AgentMemory-owned writes."
    certification_status = "experimental"
    certification_harness_classes = ("test_claude_memory_provider.ClaudeMemoryProviderHarnessTests",)
    certification_related_test_modules = (
        "test_claude_memory_provider",
        "test_agentmemory_runtime",
    )
    onboarding_order = 30

    @classmethod
    def default_provider_config(cls, *, runtime_dir: str) -> dict[str, Any]:
        start_path = Path.cwd().resolve()
        resolved_root = _discover_git_root(start_path)
        return {
            "project_root": str(start_path),
            "user_claude_dir": str(Path.home() / ".claude"),
            "auto_memory_dir": "",
            "include_user_memory": True,
            "include_auto_memory": True,
            "agentmemory_write_dir": str(resolved_root / ".claude" / "rules" / "agentmemory"),
            "default_limit": 100,
        }

    @classmethod
    def configure_parser(cls, parser) -> None:
        parser.add_argument("--project-root", help="Root or working directory to scan for Claude project memory")
        parser.add_argument("--user-claude-dir", help="Override the user-level Claude configuration directory")
        parser.add_argument("--auto-memory-dir", help="Override the Claude auto-memory directory for the active project")
        parser.add_argument("--agentmemory-write-dir", help="Override the AgentMemory-owned Claude write directory")
        parser.add_argument(
            "--no-user-memory",
            action="store_true",
            help="Disable reading user-level Claude memory from ~/.claude",
        )
        parser.add_argument(
            "--no-auto-memory",
            action="store_true",
            help="Disable reading Claude auto-memory for the active project",
        )

    @classmethod
    def apply_cli_configuration(cls, *, provider_config: dict[str, Any], args) -> bool:
        changed = False
        if getattr(args, "project_root", None):
            provider_config["project_root"] = args.project_root
            changed = True
        if getattr(args, "user_claude_dir", None):
            provider_config["user_claude_dir"] = args.user_claude_dir
            changed = True
        if getattr(args, "auto_memory_dir", None):
            provider_config["auto_memory_dir"] = args.auto_memory_dir
            changed = True
        if getattr(args, "agentmemory_write_dir", None):
            provider_config["agentmemory_write_dir"] = args.agentmemory_write_dir
            changed = True
        if getattr(args, "no_user_memory", False):
            provider_config["include_user_memory"] = False
            changed = True
        if getattr(args, "no_auto_memory", False):
            provider_config["include_auto_memory"] = False
            changed = True
        return changed

    def capabilities(self) -> ProviderCapabilities:
        return {
            "supports_semantic_search": False,
            "supports_text_search": True,
            "supports_filters": False,
            "supports_metadata_filters": False,
            "supports_rerank": False,
            "supports_update": False,
            "supports_delete": False,
            "supports_scopeless_list": True,
            "requires_scope_for_list": False,
            "requires_scope_for_search": False,
            "supports_owner_process_mode": False,
            "supports_scope_inventory": False,
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
            "delete_semantics": "provider_defined",
            "filter_semantics": "provider_defined",
            "metadata_value_policy": "json_object",
            "supports_background_ingest": False,
            "supports_remote_transport": False,
        }

    @property
    def configured_start_path(self) -> Path:
        raw = self.provider_config.get("project_root") or Path.cwd()
        return Path(raw).expanduser().resolve()

    @property
    def resolved_project_root(self) -> Path:
        return _discover_git_root(self.configured_start_path)

    @property
    def user_claude_dir(self) -> Path:
        raw = self.provider_config.get("user_claude_dir") or (Path.home() / ".claude")
        return Path(raw).expanduser().resolve()

    @property
    def include_user_memory(self) -> bool:
        return bool(self.provider_config.get("include_user_memory", True))

    @property
    def include_auto_memory(self) -> bool:
        return bool(self.provider_config.get("include_auto_memory", True))

    @property
    def auto_memory_dir(self) -> Path:
        configured = str(self.provider_config.get("auto_memory_dir") or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        project_key = _normalize_claude_project_key(self.resolved_project_root)
        return (self.user_claude_dir / "projects" / project_key / "memory").resolve()

    @property
    def write_dir(self) -> Path:
        configured = str(self.provider_config.get("agentmemory_write_dir") or "").strip()
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = self.resolved_project_root / path
            return path.resolve()
        return (self.resolved_project_root / ".claude" / "rules" / "agentmemory").resolve()

    @property
    def default_limit(self) -> int:
        return int(self.provider_config.get("default_limit", 100))

    def _coerce_limit(self, value: Any, *, default: int) -> int:
        try:
            limit = int(default if value is None else value)
        except (TypeError, ValueError) as exc:
            raise ProviderValidationError("Invalid limit for Claude Memory provider.") from exc
        return max(limit, 1)

    def _normalized_messages(self, messages) -> str:
        parts: list[str] = []
        for item in messages:
            content = item.get("content") if isinstance(item, dict) else str(item)
            if content:
                parts.append(str(content))
        return "\n".join(parts).strip()

    def _score(self, query: str, text: str) -> float:
        query_l = query.lower().strip()
        if not query_l:
            return 0.0
        text_l = text.lower()
        if query_l in text_l:
            return 1.0
        query_tokens = {token for token in query_l.split() if token}
        if not query_tokens:
            return 0.0
        text_tokens = {token for token in text_l.split() if token}
        overlap = len(query_tokens & text_tokens)
        return overlap / len(query_tokens)

    def _header_payload(self, lines: list[str]) -> tuple[dict[str, Any], list[str]]:
        if not lines:
            return {}, lines
        first = lines[0].strip()
        if not (first.startswith(_AGENTMEMORY_HEADER_PREFIX) and first.endswith(_AGENTMEMORY_HEADER_SUFFIX)):
            return {}, lines
        payload_raw = first[len(_AGENTMEMORY_HEADER_PREFIX) : -len(_AGENTMEMORY_HEADER_SUFFIX)]
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            return {}, lines
        if not isinstance(payload, dict):
            return {}, lines
        return payload, lines[1:]

    def _stable_record_id(self, *, source_kind: str, path: Path, heading_path: str | None) -> str:
        digest = hashlib.sha256(
            f"{self.provider_name}:{source_kind}:{path.as_posix()}:{heading_path or ''}".encode("utf-8")
        ).hexdigest()
        return f"cmem_{digest[:24]}"

    def _record_from_section(
        self,
        *,
        path: Path,
        source_kind: str,
        origin_surface: str,
        managed_by_agentmemory: bool,
        persisted: dict[str, Any],
        heading_path: str | None,
        memory: str,
        created_at: str,
        updated_at: str,
    ) -> MemoryRecord:
        persisted_metadata = persisted.get("metadata") if isinstance(persisted.get("metadata"), dict) else {}
        metadata = dict(persisted_metadata)
        metadata.update(
            {
                "source_kind": source_kind,
                "source_path": str(path),
                "heading_path": heading_path,
                "read_only": not managed_by_agentmemory,
                "origin_surface": origin_surface,
            }
        )
        return {
            "id": self._stable_record_id(source_kind=source_kind, path=path, heading_path=heading_path),
            "memory": memory,
            "metadata": metadata,
            "user_id": persisted.get("user_id"),
            "agent_id": persisted.get("agent_id"),
            "run_id": persisted.get("run_id"),
            "memory_type": persisted.get("memory_type"),
            "created_at": created_at,
            "updated_at": updated_at,
            "provider": self.provider_name,
            "raw": {
                "source_path": str(path),
                "heading_path": heading_path,
                "origin_surface": origin_surface,
                "source_kind": source_kind,
                "managed_by_agentmemory": managed_by_agentmemory,
            },
        }

    def _parse_sections(self, *, path: Path, source_kind: str, origin_surface: str) -> list[MemoryRecord]:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="replace")
        stat = path.stat()
        default_created_at = _utc_iso_from_timestamp(stat.st_ctime)
        default_updated_at = _utc_iso_from_timestamp(stat.st_mtime)
        lines = content.splitlines()
        persisted, visible_lines = self._header_payload(lines)
        managed_by_agentmemory = path.is_relative_to(self.write_dir)
        created_at = str(persisted.get("created_at") or default_created_at)
        updated_at = str(persisted.get("updated_at") or default_updated_at)

        headings: list[tuple[int, int, str, str]] = []
        stack: list[tuple[int, str]] = []
        for index, line in enumerate(visible_lines):
            match = _HEADING_RE.match(line)
            if not match:
                continue
            level = len(match.group(1))
            title = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            headings.append((index, level, title, " / ".join(item[1] for item in stack)))

        if not headings:
            memory = "\n".join(visible_lines).strip()
            return [
                self._record_from_section(
                    path=path,
                    source_kind=source_kind,
                    origin_surface=origin_surface,
                    managed_by_agentmemory=managed_by_agentmemory,
                    persisted=persisted,
                    heading_path=None,
                    memory=memory,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            ]

        records: list[MemoryRecord] = []
        for idx, (start_index, level, _title, heading_path) in enumerate(headings):
            end_index = len(visible_lines)
            for next_start, next_level, _next_title, _next_path in headings[idx + 1 :]:
                if next_level <= level:
                    end_index = next_start
                    break
            section_body = "\n".join(visible_lines[start_index + 1 : end_index]).strip()
            section_memory = section_body or visible_lines[start_index].strip()
            records.append(
                self._record_from_section(
                    path=path,
                    source_kind=source_kind,
                    origin_surface=origin_surface,
                    managed_by_agentmemory=managed_by_agentmemory,
                    persisted=persisted,
                    heading_path=heading_path,
                    memory=section_memory,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
        return records

    def _discover_sources(self) -> list[tuple[Path, str, str]]:
        sources: list[tuple[Path, str, str]] = []
        seen: set[Path] = set()

        start = self.configured_start_path
        root = self.resolved_project_root
        current = start if start.is_dir() else start.parent
        chain = [current]
        while current != root and root in current.parents:
            current = current.parent
            chain.append(current)
        if root not in chain:
            chain.append(root)
        for directory in chain:
            for filename, source_kind in (("CLAUDE.md", "claude_md"), ("CLAUDE.local.md", "claude_local_md")):
                candidate = directory / filename
                if candidate.exists() and candidate.suffix.lower() == ".md":
                    resolved = candidate.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        sources.append((resolved, source_kind, "project_walkup"))

        dot_claude = root / ".claude" / "CLAUDE.md"
        if dot_claude.exists():
            resolved = dot_claude.resolve()
            if resolved not in seen:
                seen.add(resolved)
                sources.append((resolved, "dot_claude_md", "project_dot_claude"))

        rules_dir = root / ".claude" / "rules"
        if rules_dir.exists():
            for candidate in sorted(rules_dir.rglob("*.md")):
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                sources.append((resolved, "rule_md", "project_rules"))

        if self.include_user_memory:
            user_file = self.user_claude_dir / "CLAUDE.md"
            if user_file.exists():
                resolved = user_file.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    sources.append((resolved, "user_claude_md", "user_memory"))
            user_rules_dir = self.user_claude_dir / "rules"
            if user_rules_dir.exists():
                for candidate in sorted(user_rules_dir.rglob("*.md")):
                    resolved = candidate.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    sources.append((resolved, "user_rule_md", "user_rules"))

        if self.include_auto_memory and self.auto_memory_dir.exists():
            for candidate in sorted(self.auto_memory_dir.rglob("*.md")):
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                source_kind = "auto_memory_index" if candidate.name == "MEMORY.md" else "auto_memory_topic"
                sources.append((resolved, source_kind, "auto_memory"))

        return sources

    def _all_records(self) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for path, source_kind, origin_surface in self._discover_sources():
            records.extend(self._parse_sections(path=path, source_kind=source_kind, origin_surface=origin_surface))
        records.sort(key=lambda item: (str(item.get("updated_at") or ""), str(item.get("id") or "")), reverse=True)
        return records

    def _surface_counts(self, records: list[MemoryRecord]) -> dict[str, int]:
        counts: dict[str, int] = {
            "project_walkup": 0,
            "project_dot_claude": 0,
            "project_rules": 0,
            "user_memory": 0,
            "user_rules": 0,
            "auto_memory": 0,
        }
        for record in records:
            metadata = record.get("metadata") or {}
            origin = str(metadata.get("origin_surface") or "")
            if origin in counts:
                counts[origin] += 1
        return counts

    def doctor_rows(self) -> list[tuple[str, str]]:
        records = self._all_records()
        counts = self._surface_counts(records)
        return [
            ("Configured path", str(self.configured_start_path)),
            ("Project root", str(self.resolved_project_root)),
            ("Write dir", str(self.write_dir)),
            ("User memory", "enabled" if self.include_user_memory else "disabled"),
            ("Auto memory", "enabled" if self.include_auto_memory else "disabled"),
            ("Record count", str(len(records))),
            ("Surface counts", json.dumps(counts, ensure_ascii=True, sort_keys=True)),
        ]

    def dependency_checks(self) -> list[dict[str, str]]:
        return [{"name": "python-stdlib", "ok": "true", "details": "built-in"}]

    def prerequisite_checks(self) -> list[dict[str, str]]:
        checks = [
            {
                "name": "project_root",
                "ok": "true" if self.resolved_project_root.exists() else "false",
                "details": str(self.resolved_project_root),
            },
            {
                "name": "write_dir_parent",
                "ok": "true" if self.write_dir.parent.exists() else "false",
                "details": str(self.write_dir.parent),
            },
        ]
        if self.include_user_memory:
            checks.append(
                {
                    "name": "user_claude_dir",
                    "ok": "true" if self.user_claude_dir.exists() else "false",
                    "details": str(self.user_claude_dir),
                }
            )
        if self.include_auto_memory:
            checks.append(
                {
                    "name": "auto_memory_dir",
                    "ok": "true" if self.auto_memory_dir.exists() else "false",
                    "details": str(self.auto_memory_dir),
                }
            )
        return checks

    def health(self) -> dict[str, Any]:
        ok = self.resolved_project_root.exists()
        return {"ok": ok, **self.runtime_info()}

    def runtime_info(self) -> dict[str, Any]:
        records = self._all_records()
        return {
            "configured_path": str(self.configured_start_path),
            "project_root": str(self.resolved_project_root),
            "user_claude_dir": str(self.user_claude_dir),
            "auto_memory_dir": str(self.auto_memory_dir),
            "agentmemory_write_dir": str(self.write_dir),
            "include_user_memory": self.include_user_memory,
            "include_auto_memory": self.include_auto_memory,
            "record_count": len(records),
            "source_counts": self._surface_counts(records),
        }

    def add_memory(self, *, messages, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None) -> MemoryRecord:
        text = self._normalized_messages(messages)
        created_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "metadata": dict(metadata or {}),
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "memory_type": memory_type,
            "infer": infer,
            "created_at": created_at,
            "updated_at": created_at,
        }
        self.write_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:8]}.md"
        target = self.write_dir / file_name
        body = (
            f"{_AGENTMEMORY_HEADER_PREFIX}{json.dumps(payload, ensure_ascii=True, separators=(',', ':'))}{_AGENTMEMORY_HEADER_SUFFIX}\n"
            "# AgentMemory Memory\n\n"
            f"{text}\n"
        )
        target.write_text(body, encoding="utf-8")
        records = self._parse_sections(path=target.resolve(), source_kind="rule_md", origin_surface="project_rules")
        if not records:
            raise ProviderValidationError("Claude Memory provider failed to materialize the new memory record.")
        return dict(records[0])

    def search_memory(self, *, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True) -> list[MemoryRecord]:
        if rerank:
            raise ProviderCapabilityError("Claude Memory provider does not support rerank.")
        if filters is not None:
            raise ProviderValidationError("Claude Memory provider does not support filters for search.")
        page_limit = self._coerce_limit(limit, default=10)
        results: list[MemoryRecord] = []
        for record in self._all_records():
            score = self._score(str(query), str(record.get("memory", "")))
            if threshold is not None and score < threshold:
                continue
            if score <= 0:
                continue
            item = dict(record)
            item["score"] = score
            results.append(item)
        results.sort(key=lambda item: (float(item.get("score", 0.0)), str(item.get("updated_at") or "")), reverse=True)
        return results[:page_limit]

    def list_memories(self, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None) -> list[MemoryRecord]:
        if filters is not None:
            raise ProviderValidationError("Claude Memory provider does not support filters for list.")
        page_limit = self._coerce_limit(limit, default=self.default_limit)
        return self._all_records()[:page_limit]

    def get_memory(self, memory_id) -> MemoryRecord:
        for record in self._all_records():
            if record.get("id") == memory_id:
                return dict(record)
        raise MemoryNotFoundError(memory_id)

    def list_scopes(self, *, limit: int = 200, kind: str | None = None, query: str | None = None) -> ScopeInventory:
        if kind is not None and kind not in {"user", "agent", "run"}:
            raise ProviderValidationError("Invalid scope kind for Claude Memory provider.")
        return {
            "provider": self.provider_name,
            "items": [],
            "totals": {"users": 0, "agents": 0, "runs": 0},
        }
