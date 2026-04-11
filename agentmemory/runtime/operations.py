from __future__ import annotations

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
from agentmemory.runtime.transport import execute_transport_operation, validate_and_build_list_kwargs, validate_and_build_search_kwargs


@dataclass(frozen=True)
class OperationSpec:
    name: str
    mcp_name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    execute: Callable[[dict[str, Any]], Any]


def _execute_health(_: dict[str, Any]) -> Any:
    return execute_transport_operation(
        use_proxy=should_proxy_to_api(),
        local_call=health,
        proxy_call=proxy_health,
    )


def _execute_add(source: dict[str, Any]) -> Any:
    kwargs = {
        "messages": source["messages"],
        "user_id": source.get("user_id"),
        "agent_id": source.get("agent_id"),
        "run_id": source.get("run_id"),
        "metadata": source.get("metadata"),
        "infer": source.get("infer", True),
        "memory_type": source.get("memory_type"),
    }
    return execute_transport_operation(
        use_proxy=should_proxy_to_api(),
        local_call=lambda: memory_add(**kwargs),
        proxy_call=lambda: proxy_add(**kwargs),
    )


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


def _execute_search(source: dict[str, Any]) -> Any:
    kwargs = validate_and_build_search_kwargs(
        provider_name=active_provider_name(),
        capabilities=active_provider_capabilities(),
        source=source,
        default_limit=10,
    )
    return execute_transport_operation(
        use_proxy=should_proxy_to_api(),
        local_call=lambda: memory_search(**kwargs),
        proxy_call=lambda: proxy_search(**kwargs),
    )


def _execute_list(source: dict[str, Any]) -> Any:
    kwargs = validate_and_build_list_kwargs(
        provider_name=active_provider_name(),
        capabilities=active_provider_capabilities(),
        source=source,
        default_limit=100,
    )
    return execute_transport_operation(
        use_proxy=should_proxy_to_api(),
        local_call=lambda: memory_list(**kwargs),
        proxy_call=lambda: proxy_list(**kwargs),
    )


def _execute_get(source: dict[str, Any]) -> Any:
    memory_id = source["memory_id"]
    return execute_transport_operation(
        use_proxy=should_proxy_to_api(),
        local_call=lambda: memory_get(memory_id),
        proxy_call=lambda: proxy_get(memory_id),
    )


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
    return execute_transport_operation(
        use_proxy=should_proxy_to_api(),
        local_call=lambda: memory_delete(memory_id=memory_id),
        proxy_call=lambda: proxy_delete(memory_id=memory_id),
    )


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
        description="Store a new memory from plain text for a user, agent, or run.",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Memory text to store."},
                "user_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "run_id": {"type": "string"},
                "metadata": {"type": "object"},
                "infer": {"type": "boolean", "default": True},
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
