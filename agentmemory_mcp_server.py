import json
import sys
import traceback
from typing import Any

from agentmemory_http_client import (
    proxy_add,
    proxy_delete,
    proxy_get,
    proxy_health,
    proxy_list,
    proxy_search,
    proxy_update,
    should_proxy_to_api,
)
from agentmemory_runtime import (
    ConfigurationError,
    health,
    memory_add,
    memory_delete,
    memory_get,
    memory_list,
    memory_search,
    memory_update,
)

SERVER_INFO = {
    "name": "agentmemory",
    "title": "AgentMemory Shared Runtime",
    "version": "1.0.0",
}
SUPPORTED_PROTOCOLS = ["2025-06-18", "2024-11-05"]

TOOLS = [
    {
        "name": "memory_health",
        "title": "Memory Health",
        "description": "Return runtime information for the shared memory service.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "memory_add",
        "title": "Add Memory",
        "description": "Store a new memory from plain text for a user, agent, or run.",
        "inputSchema": {
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
    },
    {
        "name": "memory_search",
        "title": "Search Memory",
        "description": "Search shared memory semantically.",
        "inputSchema": {
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
    },
    {
        "name": "memory_list",
        "title": "List Memories",
        "description": "List memories for a user, agent, or run.",
        "inputSchema": {
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
    },
    {
        "name": "memory_get",
        "title": "Get Memory",
        "description": "Get one memory by id.",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_update",
        "title": "Update Memory",
        "description": "Update a memory by id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "data": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["memory_id", "data"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_delete",
        "title": "Delete Memory",
        "description": "Delete a memory by id.",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
            "additionalProperties": False,
        },
    },
]


def write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def make_text_result(payload: Any, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=True, indent=2, default=str)}],
        "structuredContent": payload if isinstance(payload, dict) else {"result": payload},
        "isError": is_error,
    }


def success(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_initialize(request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    protocol_version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
    result = {
        "protocolVersion": protocol_version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": SERVER_INFO,
    }
    return success(request_id, result)


def handle_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "memory_health":
        return make_text_result(proxy_health() if should_proxy_to_api() else health())
    if name == "memory_add":
        kwargs = dict(
            messages=[{"role": "user", "content": arguments["text"]}],
            user_id=arguments.get("user_id"),
            agent_id=arguments.get("agent_id"),
            run_id=arguments.get("run_id"),
            metadata=arguments.get("metadata"),
            infer=arguments.get("infer", True),
            memory_type=arguments.get("memory_type"),
        )
        payload = proxy_add(**kwargs) if should_proxy_to_api() else memory_add(**kwargs)
        return make_text_result(payload)
    if name == "memory_search":
        kwargs = dict(
            query=arguments["query"],
            user_id=arguments.get("user_id"),
            agent_id=arguments.get("agent_id"),
            run_id=arguments.get("run_id"),
            limit=arguments.get("limit", 10),
            filters=arguments.get("filters"),
            threshold=arguments.get("threshold"),
            rerank=arguments.get("rerank", True),
        )
        payload = proxy_search(**kwargs) if should_proxy_to_api() else memory_search(**kwargs)
        return make_text_result(payload)
    if name == "memory_list":
        kwargs = dict(
            user_id=arguments.get("user_id"),
            agent_id=arguments.get("agent_id"),
            run_id=arguments.get("run_id"),
            limit=arguments.get("limit", 100),
            filters=arguments.get("filters"),
        )
        payload = proxy_list(**kwargs) if should_proxy_to_api() else memory_list(**kwargs)
        return make_text_result(payload)
    if name == "memory_get":
        return make_text_result(proxy_get(arguments["memory_id"]) if should_proxy_to_api() else memory_get(arguments["memory_id"]))
    if name == "memory_update":
        kwargs = {"memory_id": arguments["memory_id"], "data": arguments["data"], "metadata": arguments.get("metadata")}
        return make_text_result(proxy_update(**kwargs) if should_proxy_to_api() else memory_update(**kwargs))
    if name == "memory_delete":
        return make_text_result(proxy_delete(memory_id=arguments["memory_id"]) if should_proxy_to_api() else memory_delete(memory_id=arguments["memory_id"]))
    raise KeyError(name)


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        return handle_initialize(request_id, params)
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return success(request_id, {})
    if method == "tools/list":
        return success(request_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            return success(request_id, handle_call(name, arguments))
        except ConfigurationError as exc:
            return success(request_id, make_text_result({"error": str(exc)}, is_error=True))
        except KeyError:
            return error(request_id, -32601, f"Unknown tool: {name}")
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            return success(request_id, make_text_result({"error": str(exc)}, is_error=True))
    if method == "resources/list":
        return success(request_id, {"resources": []})
    if method == "prompts/list":
        return success(request_id, {"prompts": []})
    if request_id is None:
        return None
    return error(request_id, -32601, f"Method not found: {method}")


def iter_messages():
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        yield json.loads(line)


def main() -> int:
    try:
        for incoming in iter_messages():
            if isinstance(incoming, list):
                responses = []
                for item in incoming:
                    response = handle_request(item)
                    if response is not None:
                        responses.append(response)
                if responses:
                    write_message(responses)
                continue

            response = handle_request(incoming)
            if response is not None:
                write_message(response)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
