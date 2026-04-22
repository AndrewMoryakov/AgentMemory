import json
import sys
import traceback
from typing import Any

from agentmemory.runtime.operation_adapters import mcp_operation_source
from agentmemory.runtime.operations import OPERATIONS_BY_MCP_NAME, mcp_tools
from agentmemory.runtime.transport import mcp_result, provider_error_payload
from agentmemory.providers.base import ProviderError, ProviderValidationError

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


def _schema_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def validate_arguments(schema: dict[str, Any], arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ProviderValidationError("MCP tool arguments must be an object.")

    if schema.get("type") == "object":
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        for field in required:
            if field not in arguments:
                raise ProviderValidationError(f"Missing required argument: {field}")

        if schema.get("additionalProperties") is False:
            extra = sorted(key for key in arguments if key not in properties)
            if extra:
                raise ProviderValidationError(f"Unexpected argument: {extra[0]}")

        for field, value in arguments.items():
            field_schema = properties.get(field)
            if not isinstance(field_schema, dict):
                continue
            expected_type = field_schema.get("type")
            if isinstance(expected_type, str) and not _schema_type_matches(value, expected_type):
                raise ProviderValidationError(f"Argument '{field}' must be {expected_type}.")
            allowed_values = field_schema.get("enum")
            if isinstance(allowed_values, list) and value not in allowed_values:
                raise ProviderValidationError(f"Argument '{field}' must be one of: {', '.join(map(str, allowed_values))}.")
            minimum = field_schema.get("minimum")
            if isinstance(minimum, (int, float)) and isinstance(value, (int, float)) and not isinstance(value, bool) and value < minimum:
                raise ProviderValidationError(f"Argument '{field}' must be >= {minimum}.")

    return arguments


def handle_call(spec: Any, name: str, arguments: Any) -> dict[str, Any]:
    validated_arguments = validate_arguments(spec.input_schema, arguments)
    return mcp_result(spec.execute(mcp_operation_source(name, validated_arguments)))


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
        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        spec = OPERATIONS_BY_MCP_NAME.get(name)
        if spec is None:
            return error(request_id, -32601, f"Unknown tool: {name}")
        try:
            return success(request_id, handle_call(spec, name, arguments))
        except ProviderError as exc:
            return success(request_id, error_result(exc))
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
