"""Shared JSON-schema-style argument validation.

Extracted from ``agentmemory.mcp`` so every surface (MCP, HTTP) can validate
raw operation input against an operation's ``input_schema`` identically. The
validation intentionally mirrors the subset of JSON Schema the operation
schemas use: ``type``, ``required``, ``enum``, ``minimum``, and
``additionalProperties: false``.
"""

from __future__ import annotations

from typing import Any

from agentmemory.providers.base import ProviderValidationError


def schema_type_matches(value: Any, expected_type: str) -> bool:
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
            if isinstance(expected_type, str) and not schema_type_matches(value, expected_type):
                raise ProviderValidationError(f"Argument '{field}' must be {expected_type}.")
            allowed_values = field_schema.get("enum")
            if isinstance(allowed_values, list) and value not in allowed_values:
                raise ProviderValidationError(
                    f"Argument '{field}' must be one of: {', '.join(map(str, allowed_values))}."
                )
            minimum = field_schema.get("minimum")
            if (
                isinstance(minimum, (int, float))
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value < minimum
            ):
                raise ProviderValidationError(f"Argument '{field}' must be >= {minimum}.")

    return arguments
