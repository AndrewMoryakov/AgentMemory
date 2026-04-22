from __future__ import annotations

import json
from typing import Any, Callable

from agentmemory.providers.base import ProviderValidationError


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
    if command == "list":
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
        return dict(payload)
    if operation_name == "list_scopes":
        return {
            "limit": int((query_params.get("limit") or ["200"])[0]),
            "kind": (query_params.get("kind") or [None])[0],
            "query": (query_params.get("query") or [None])[0],
        }
    if operation_name == "search":
        return dict(payload)
    if operation_name == "update":
        return dict(payload)
    if operation_name == "list":
        filters = None
        filters_param = (query_params.get("filters") or [None])[0]
        if filters_param:
            try:
                filters = json.loads(filters_param)
            except json.JSONDecodeError as exc:
                raise ProviderValidationError(f"Invalid JSON: {exc.msg}") from exc
        return {
            "user_id": (query_params.get("user_id") or [None])[0],
            "agent_id": (query_params.get("agent_id") or [None])[0],
            "run_id": (query_params.get("run_id") or [None])[0],
            "limit": int((query_params.get("limit") or ["100"])[0]),
            "filters": filters,
        }
    if operation_name in {"get", "delete"}:
        return {"memory_id": path_params["memory_id"]}
    raise ProviderValidationError(f"Unsupported HTTP operation: {operation_name}")
