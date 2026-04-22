from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from agentmemory.runtime.http_client import (
    proxy_add,
    proxy_delete,
    proxy_get,
    proxy_health,
    proxy_list_scopes,
    proxy_list,
    proxy_search,
    proxy_update,
    should_proxy_to_api,
)
from agentmemory.runtime.config import (
    active_provider_capabilities,
    active_provider_name,
    health,
    memory_add,
    memory_delete,
    memory_get,
    memory_list_scopes,
    memory_list,
    memory_search,
    memory_update,
)
from agentmemory.runtime import lifecycle as lifecycle_module
from agentmemory.runtime import metrics as metrics_registry
from agentmemory.runtime import portability as portability_module
from agentmemory.runtime import reconcile as reconcile_module
from agentmemory.runtime.transport import execute_transport_operation, validate_and_build_list_kwargs, validate_and_build_search_kwargs
from agentmemory.providers.base import MemoryNotFoundError

LOGGER = logging.getLogger(__name__)


@dataclass
class OperationSpec:
    name: str
    mcp_name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    # Public callable. __post_init__ rewrites it to a metrics-timed wrapper
    # so every call through OPERATIONS[...].execute(source) — HTTP, MCP, or
    # CLI — records latency + success/error per operation name.
    execute: Callable[[dict[str, Any]], Any]

    def __post_init__(self) -> None:
        raw = self.execute
        name = self.name

        def _instrumented(source: dict[str, Any]) -> Any:
            with metrics_registry.timed(name):
                return raw(source)

        self.execute = _instrumented


def _execute_health(_: dict[str, Any]) -> Any:
    return execute_transport_operation(
        use_proxy=should_proxy_to_api(),
        local_call=health,
        proxy_call=proxy_health,
    )


def _original_input_text(source: dict[str, Any]) -> str | None:
    raw = source.get("messages")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict):
            content = first.get("content")
            if isinstance(content, str):
                return content
    text = source.get("text")
    return text if isinstance(text, str) else None


DEDUP_SCORE_THRESHOLD = 0.92
TTL_REFILL_MAX_ATTEMPTS = 4


def _maybe_dedup_existing(source: dict[str, Any]) -> dict[str, Any] | None:
    """Return a pre-existing record that matches the add candidate closely
    enough to skip the insert. Guarded by dedup=true in source.

    Returns None if dedup is disabled, not supported, the scope is missing,
    or no candidate clears the similarity threshold.
    """
    if not bool(source.get("dedup", False)):
        return None
    query_text = _original_input_text(source)
    if not isinstance(query_text, str) or not query_text.strip():
        return None
    scope_fields = {
        "user_id": source.get("user_id"),
        "agent_id": source.get("agent_id"),
        "run_id": source.get("run_id"),
    }
    if not any(v for v in scope_fields.values()):
        # Dedup without a scope would compare against the entire store; that's
        # too expensive and ambiguous for a default value. Caller must scope.
        return None
    capabilities = active_provider_capabilities()
    if not capabilities.get("supports_semantic_search"):
        return None
    try:
        kwargs = validate_and_build_search_kwargs(
            provider_name=active_provider_name(),
            capabilities=capabilities,
            source={"query": query_text, **scope_fields, "limit": 3},
            default_limit=3,
        )
    except Exception:
        return None
    try:
        hits = execute_transport_operation(
            use_proxy=should_proxy_to_api(),
            local_call=lambda: memory_search(**kwargs),
            proxy_call=lambda: proxy_search(**kwargs),
        )
    except Exception as exc:
        metrics_registry.record_event(name="memory_add.dedup_probe_failed")
        LOGGER.warning(
            "memory_add dedup probe failed",
            extra={"error_type": exc.__class__.__name__},
            exc_info=True,
        )
        return None
    if not isinstance(hits, list):
        return None
    hits = lifecycle_module.filter_unexpired(hits)
    for hit in hits:
        score = hit.get("score") if isinstance(hit, dict) else None
        if isinstance(score, (int, float)) and float(score) >= DEDUP_SCORE_THRESHOLD:
            enriched = dict(hit)
            enriched["dedup_hit"] = True
            enriched["dedup_score"] = float(score)
            return enriched
    return None


def _execute_add(source: dict[str, Any]) -> Any:
    deduped = _maybe_dedup_existing(source)
    if deduped is not None:
        metrics_registry.record_event(name="memory_add.dedup_hit")
        return deduped

    infer_requested = bool(source.get("infer", False))
    # Lifecycle: caller may set metadata.expires_at (ISO) or metadata.ttl_seconds.
    # Normalize to a single expires_at field so downstream readers have one key
    # to check. ttl_seconds is dropped after resolution.
    normalized_metadata = lifecycle_module.apply_expiry_to_metadata(source.get("metadata"))
    kwargs = {
        "messages": source["messages"],
        "user_id": source.get("user_id"),
        "agent_id": source.get("agent_id"),
        "run_id": source.get("run_id"),
        "metadata": normalized_metadata,
        "infer": infer_requested,
        "memory_type": source.get("memory_type"),
    }
    result = execute_transport_operation(
        use_proxy=should_proxy_to_api(),
        local_call=lambda: memory_add(**kwargs),
        proxy_call=lambda: proxy_add(**kwargs),
    )
    metrics_registry.record_event(name="memory_add.inserted")
    if infer_requested and isinstance(result, dict):
        original = _original_input_text(source)
        stored = result.get("memory")
        if isinstance(original, str) and isinstance(stored, str) and original != stored:
            enriched = dict(result)
            enriched["transformed"] = True
            enriched["original_text"] = original
            enriched["stored_text"] = stored
            return enriched
    return result


def _execute_list_scopes(source: dict[str, Any]) -> Any:
    kwargs = {
        "limit": source.get("limit", 200),
        "kind": source.get("kind"),
        "query": source.get("query"),
    }
    return execute_transport_operation(
        use_proxy=should_proxy_to_api(),
        local_call=lambda: memory_list_scopes(**kwargs),
        proxy_call=lambda: proxy_list_scopes(**kwargs),
    )


def _execute_export(source: dict[str, Any]) -> Any:
    return portability_module.export_memories(path=source["path"])


def _execute_import(source: dict[str, Any]) -> Any:
    return portability_module.import_memories(path=source["path"])


def _filter_unexpired_with_limit_refill(
    *,
    kwargs: dict[str, Any],
    default_limit: int,
    fetch: Callable[[dict[str, Any]], Any],
) -> Any:
    requested_limit = kwargs.get("limit")
    if not isinstance(requested_limit, int) or requested_limit <= 0:
        requested_limit = default_limit

    current_limit = requested_limit
    last_unexpired: list[dict[str, Any]] = []

    for _ in range(TTL_REFILL_MAX_ATTEMPTS):
        attempt_kwargs = dict(kwargs)
        attempt_kwargs["limit"] = current_limit
        result = fetch(attempt_kwargs)
        if not isinstance(result, list):
            return result

        unexpired = lifecycle_module.filter_unexpired(result)
        if len(unexpired) >= requested_limit:
            return unexpired[:requested_limit]

        last_unexpired = unexpired
        if len(result) < current_limit:
            return unexpired

        current_limit *= 2

    return last_unexpired


def _execute_search(source: dict[str, Any]) -> Any:
    kwargs = validate_and_build_search_kwargs(
        provider_name=active_provider_name(),
        capabilities=active_provider_capabilities(),
        source=source,
        default_limit=10,
    )
    return _filter_unexpired_with_limit_refill(
        kwargs=kwargs,
        default_limit=10,
        fetch=lambda attempt_kwargs: execute_transport_operation(
            use_proxy=should_proxy_to_api(),
            local_call=lambda: memory_search(**attempt_kwargs),
            proxy_call=lambda: proxy_search(**attempt_kwargs),
        ),
    )


def _execute_list(source: dict[str, Any]) -> Any:
    kwargs = validate_and_build_list_kwargs(
        provider_name=active_provider_name(),
        capabilities=active_provider_capabilities(),
        source=source,
        default_limit=100,
    )
    return _filter_unexpired_with_limit_refill(
        kwargs=kwargs,
        default_limit=100,
        fetch=lambda attempt_kwargs: execute_transport_operation(
            use_proxy=should_proxy_to_api(),
            local_call=lambda: memory_list(**attempt_kwargs),
            proxy_call=lambda: proxy_list(**attempt_kwargs),
        ),
    )


def _execute_reconcile(source: dict[str, Any]) -> Any:
    kwargs = validate_and_build_list_kwargs(
        provider_name=active_provider_name(),
        capabilities=active_provider_capabilities(),
        source=source,
        default_limit=100,
    )
    records = _filter_unexpired_with_limit_refill(
        kwargs=kwargs,
        default_limit=100,
        fetch=lambda attempt_kwargs: execute_transport_operation(
            use_proxy=should_proxy_to_api(),
            local_call=lambda: memory_list(**attempt_kwargs),
            proxy_call=lambda: proxy_list(**attempt_kwargs),
        ),
    )
    if not isinstance(records, list):
        records = []
    conflicts = reconcile_module.find_conflicts(records)
    return {
        "provider": active_provider_name(),
        "scope": {
            "user_id": kwargs.get("user_id"),
            "agent_id": kwargs.get("agent_id"),
            "run_id": kwargs.get("run_id"),
        },
        "checked": len(records),
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
    }


def _execute_get(source: dict[str, Any]) -> Any:
    memory_id = source["memory_id"]
    result = execute_transport_operation(
        use_proxy=should_proxy_to_api(),
        local_call=lambda: memory_get(memory_id),
        proxy_call=lambda: proxy_get(memory_id),
    )
    if isinstance(result, dict) and lifecycle_module.is_expired(result):
        # Treat expired records as if the sweeper already removed them: the
        # caller will get MemoryNotFoundError, matching hard_delete semantics.
        raise MemoryNotFoundError(memory_id)
    return result


def _execute_update(source: dict[str, Any]) -> Any:
    kwargs = {
        "memory_id": source["memory_id"],
        "data": source["data"],
        "metadata": source.get("metadata"),
    }
    return execute_transport_operation(
        use_proxy=should_proxy_to_api(),
        local_call=lambda: memory_update(**kwargs),
        proxy_call=lambda: proxy_update(**kwargs),
    )


def _execute_delete(source: dict[str, Any]) -> Any:
    memory_id = source["memory_id"]
    try:
        return execute_transport_operation(
            use_proxy=should_proxy_to_api(),
            local_call=lambda: memory_delete(memory_id=memory_id),
            proxy_call=lambda: proxy_delete(memory_id=memory_id),
        )
    except MemoryNotFoundError:
        # Idempotent delete: a second delete on an already-removed record is
        # a success-with-no-op, not a transport failure. The report "v2"
        # explicitly allows this shape (deleted=false, already_absent=true).
        return {
            "id": memory_id,
            "deleted": False,
            "already_absent": True,
            "provider": active_provider_name(),
        }


OPERATIONS: dict[str, OperationSpec] = {
    "health": OperationSpec(
        name="health",
        mcp_name="memory_health",
        title="Memory Health",
        description="Return runtime information for the shared memory service.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        execute=_execute_health,
    ),
    "add": OperationSpec(
        name="add",
        mcp_name="memory_add",
        title="Add Memory",
        description=(
            "Store a new memory for a user, agent, or run. By default the text is stored "
            "verbatim (infer=false). Pass infer=true to let the provider's LLM extract, "
            "rewrite, or deduplicate the text before storage; when that happens the response "
            "includes transformed=true with original_text and stored_text so the rewrite "
            "is observable. infer=true costs one LLM call per write. Optional lifecycle: "
            "set metadata.ttl_seconds (positive number) or metadata.expires_at (ISO 8601 UTC) "
            "to have this memory auto-expire — expired records are filtered from list/search "
            "and hard-deleted by the background sweeper."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Memory text to store."},
                "user_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "run_id": {"type": "string"},
                "metadata": {"type": "object"},
                "infer": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "When false (default) the provider stores the input text verbatim. "
                        "When true, the provider may run an LLM over the input to extract or "
                        "rewrite memory-worthy content; stored text may differ from input."
                    ),
                },
                "dedup": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "When true, before inserting run a semantic search within the same "
                        "scope and if any existing memory matches the input above the "
                        "similarity threshold, return that record (with dedup_hit=true and "
                        "dedup_score) instead of creating a duplicate. Requires user_id, "
                        "agent_id, or run_id and a provider with semantic search."
                    ),
                },
                "memory_type": {"type": "string"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        execute=_execute_add,
    ),
    "list_scopes": OperationSpec(
        name="list_scopes",
        mcp_name="memory_list_scopes",
        title="List Scopes",
        description="List known user, agent, and run scopes for the active provider.",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 200, "minimum": 1},
                "kind": {"type": "string", "enum": ["user", "agent", "run"]},
                "query": {"type": "string"},
            },
            "additionalProperties": False,
        },
        execute=_execute_list_scopes,
    ),
    "export": OperationSpec(
        name="export",
        mcp_name="memory_export",
        title="Export Memories",
        description=(
            "Export memories to a provider-neutral JSONL file on the current machine. "
            "The operation walks scope inventory and writes canonical memory records; "
            "the path is resolved on the process executing the tool."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        execute=_execute_export,
    ),
    "import": OperationSpec(
        name="import",
        mcp_name="memory_import",
        title="Import Memories",
        description=(
            "Import memories from a provider-neutral JSONL file on the current machine. "
            "Records are replayed through memory_add with infer=false for round-trip fidelity."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        execute=_execute_import,
    ),
    "search": OperationSpec(
        name="search",
        mcp_name="memory_search",
        title="Search Memory",
        description="Search shared memory semantically.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "user_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "run_id": {"type": "string"},
                "limit": {"type": "integer", "default": 10, "minimum": 1},
                "threshold": {"type": "number"},
                "filters": {"type": "object"},
                "rerank": {"type": "boolean", "default": True},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        execute=_execute_search,
    ),
    "list": OperationSpec(
        name="list",
        mcp_name="memory_list",
        title="List Memories",
        description="List memories for a user, agent, or run.",
        input_schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "run_id": {"type": "string"},
                "limit": {"type": "integer", "default": 100, "minimum": 1},
                "filters": {"type": "object"},
            },
            "additionalProperties": False,
        },
        execute=_execute_list,
    ),
    "reconcile": OperationSpec(
        name="reconcile",
        mcp_name="memory_reconcile",
        title="Reconcile Memories",
        description=(
            "Read-only memory hygiene check. Lists memories in a scope and returns likely "
            "conflicting claim pairs without modifying storage."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "run_id": {"type": "string"},
                "limit": {"type": "integer", "default": 100, "minimum": 1},
                "filters": {"type": "object"},
            },
            "additionalProperties": False,
        },
        execute=_execute_reconcile,
    ),
    "get": OperationSpec(
        name="get",
        mcp_name="memory_get",
        title="Get Memory",
        description="Get one memory by id.",
        input_schema={
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
            "additionalProperties": False,
        },
        execute=_execute_get,
    ),
    "update": OperationSpec(
        name="update",
        mcp_name="memory_update",
        title="Update Memory",
        description="Update a memory by id.",
        input_schema={
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "data": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["memory_id", "data"],
            "additionalProperties": False,
        },
        execute=_execute_update,
    ),
    "delete": OperationSpec(
        name="delete",
        mcp_name="memory_delete",
        title="Delete Memory",
        description="Delete a memory by id.",
        input_schema={
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
            "additionalProperties": False,
        },
        execute=_execute_delete,
    ),
}

OPERATIONS_BY_MCP_NAME = {spec.mcp_name: spec for spec in OPERATIONS.values()}


def mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.mcp_name,
            "title": spec.title,
            "description": spec.description,
            "inputSchema": spec.input_schema,
        }
        for spec in OPERATIONS.values()
    ]
