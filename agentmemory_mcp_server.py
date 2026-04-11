import json
import sys
import traceback
from typing import Any

from agentmemory_operation_adapters import mcp_operation_source
from agentmemory_operations import OPERATIONS_BY_MCP_NAME, mcp_tools
from agentmemory_transport import mcp_result, provider_error_payload
from memory_provider import ProviderError

SERVER_INFO = {
    "name": "agentmemory",
    "title": "AgentMemory Shared Runtime",
    "version": "1.0.0",
}
SUPPORTED_PROTOCOLS = ["2025-06-18", "2024-11-05"]

TOOLS = mcp_tools()


def write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=True) + "\n")
    sys.stdout.flush()


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
    spec = OPERATIONS_BY_MCP_NAME.get(name)
    if spec is None:
        raise KeyError(name)
    return mcp_result(spec.execute(mcp_operation_source(name, arguments)))


def error_result(exc: ProviderError) -> dict[str, Any]:
    return mcp_result(provider_error_payload(exc), is_error=True)


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
        except ProviderError as exc:
            return success(request_id, error_result(exc))
        except KeyError:
            return error(request_id, -32601, f"Unknown tool: {name}")
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            return success(request_id, mcp_result({"error_type": "InternalError", "message": str(exc)}, is_error=True))
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
