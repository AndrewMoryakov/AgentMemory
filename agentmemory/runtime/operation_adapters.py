from __future__ import annotations

import json
from typing import Any, Callable

from agentmemory.providers.base import ProviderValidationError
from agentmemory.runtime.schema_validation import validate_arguments


def _input_schema_for(operation_name: str) -> dict[str, Any] | None:
    # Imported lazily to keep adapters importable even if the operations
    # registry (which pulls in providers/config) is mid-initialization; there
    # is no static import cycle today, but a lazy lookup keeps it robust.
    from agentmemory.runtime.operations import OPERATIONS

    spec = OPERATIONS.get(operation_name)
    return spec.input_schema if spec is not None else None


def _validate_http_payload(operation_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a client-supplied request body against the op schema.

    Mirrors MCP: the raw payload is validated as-is so explicit nulls for
    typed optional fields are rejected exactly as MCP rejects them.
    """
    schema = _input_schema_for(operation_name)
    if schema is not None:
        validate_arguments(schema, payload)
    return payload


def _validate_http_source(operation_name: str, source: dict[str, Any]) -> dict[str, Any]:
    """Validate an adapter-built source (from query/path params).

    Query/path adapters synthesize optional fields as explicit None to keep a
    stable source shape; the schema treats those fields as simply absent (they
    are not in `required`). Validate against the present values only so a None
    placeholder is not mistaken for a bad type, then return the full source.
    """
    schema = _input_schema_for(operation_name)
    if schema is not None:
        present = {key: value for key, value in source.items() if value is not None}
        validate_arguments(schema, present)
    return source


def operation_name_for_mcp_tool(tool_name: str) -> str:
    if not tool_name.startswith("memory_"):
        raise ProviderValidationError(f"Unsupported MCP tool: {tool_name}")
    return tool_name.removeprefix("memory_")


def cli_operation_source(
    command: str,
    args: Any,
    *,
    parse_json_arg: Callable[[str | None], Any],
) -> dict[str, Any]:
    if command == "health":
        return {}
    if command == "list-scopes":
        return {
            "limit": args.limit,
            "kind": args.kind,
            "query": args.query,
        }
    if command == "list-scopes-page":
        return {
            "limit": args.limit,
            "cursor": args.cursor,
            "kind": args.kind,
            "query": args.query,
        }
    if command == "export":
        return {"path": args.path}
    if command == "import":
        return {"path": args.path}
    if command == "add":
        return {
            "messages": [{"role": "user", "content": text} for text in args.message],
            "user_id": args.user_id,
            "agent_id": args.agent_id,
            "run_id": args.run_id,
            "metadata": parse_json_arg(args.metadata),
            "infer": bool(getattr(args, "infer", False)),
            "memory_type": args.memory_type,
        }
    if command == "search":
        return {
            "query": args.query,
            "user_id": args.user_id,
            "agent_id": args.agent_id,
            "run_id": args.run_id,
            "limit": args.limit,
            "filters": parse_json_arg(args.filters),
            "threshold": args.threshold,
            "rerank": not args.no_rerank,
        }
    if command == "search-page":
        return {
            "query": args.query,
            "user_id": args.user_id,
            "agent_id": args.agent_id,
            "run_id": args.run_id,
            "limit": args.limit,
            "cursor": args.cursor,
            "filters": parse_json_arg(args.filters),
            "threshold": args.threshold,
            "rerank": not args.no_rerank,
        }
    if command == "list":
        return {
            "user_id": args.user_id,
            "agent_id": args.agent_id,
            "run_id": args.run_id,
            "limit": args.limit,
            "filters": parse_json_arg(args.filters),
        }
    if command == "list-page":
        return {
            "user_id": args.user_id,
            "agent_id": args.agent_id,
            "run_id": args.run_id,
            "limit": args.limit,
            "cursor": args.cursor,
            "filters": parse_json_arg(args.filters),
        }
    if command == "reconcile":
        return {
            "user_id": args.user_id,
            "agent_id": args.agent_id,
            "run_id": args.run_id,
            "limit": args.limit,
            "filters": parse_json_arg(args.filters),
        }
    if command == "get":
        return {"memory_id": args.memory_id}
    if command == "update":
        return {
            "memory_id": args.memory_id,
            "data": args.data,
            "metadata": parse_json_arg(args.metadata),
        }
    if command == "delete":
        return {"memory_id": args.memory_id}
    raise ProviderValidationError(f"Unsupported CLI command: {command}")


def mcp_operation_source(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    operation_name = operation_name_for_mcp_tool(tool_name)
    source = dict(arguments)
    if operation_name == "add":
        source["messages"] = [{"role": "user", "content": arguments["text"]}]
    return source


def http_operation_source(
    operation_name: str,
    *,
    payload: dict[str, Any] | None = None,
    query_params: dict[str, list[str]] | None = None,
    path_params: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    query_params = query_params or {}
    path_params = path_params or {}

    if operation_name == "health":
        return {}
    if operation_name == "add":
        # Validate the RAW payload (which carries `text`, not `messages`) against
        # the schema exactly as MCP does, THEN synthesize the `messages` list the
        # `_execute_add` handler reads. Order matters: validation must see `text`.
        _validate_http_payload(operation_name, payload)
        source = dict(payload)
        source["messages"] = [{"role": "user", "content": payload["text"]}]
        return source
    if operation_name == "list_scopes":
        return _validate_http_source(operation_name, {
            "limit": int((query_params.get("limit") or ["200"])[0]),
            "kind": (query_params.get("kind") or [None])[0],
            "query": (query_params.get("query") or [None])[0],
        })
    if operation_name == "list_scopes_page":
        return _validate_http_source(operation_name, {
            "limit": int((query_params.get("limit") or ["200"])[0]),
            "cursor": (query_params.get("cursor") or [None])[0],
            "kind": (query_params.get("kind") or [None])[0],
            "query": (query_params.get("query") or [None])[0],
        })
    if operation_name in {"search", "search_page"}:
        return _validate_http_payload(operation_name, dict(payload))
    if operation_name == "update":
        return _validate_http_payload(operation_name, dict(payload))
    if operation_name in {"list", "list_page"}:
        filters = None
        filters_param = (query_params.get("filters") or [None])[0]
        if filters_param:
            try:
                filters = json.loads(filters_param)
            except json.JSONDecodeError as exc:
                raise ProviderValidationError(f"Invalid JSON: {exc.msg}") from exc
        return _validate_http_source(operation_name, {
            "user_id": (query_params.get("user_id") or [None])[0],
            "agent_id": (query_params.get("agent_id") or [None])[0],
            "run_id": (query_params.get("run_id") or [None])[0],
            "limit": int((query_params.get("limit") or ["100"])[0]),
            **({"cursor": (query_params.get("cursor") or [None])[0]} if operation_name == "list_page" else {}),
            "filters": filters,
        })
    if operation_name in {"get", "delete"}:
        return {"memory_id": path_params["memory_id"]}
    raise ProviderValidationError(f"Unsupported HTTP operation: {operation_name}")
