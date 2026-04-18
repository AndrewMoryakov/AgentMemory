from __future__ import annotations

import json
from typing import Any, Callable

from agentmemory.providers.base import (
    MemoryNotFoundError,
    ProviderCapabilityError,
    ProviderCapabilities,
    ProviderConfigurationError,
    ProviderError,
    ProviderScopeRequiredError,
    ProviderUnavailableError,
    ProviderValidationError,
)


ERROR_TYPE_MAP: dict[str, type[ProviderError]] = {
    "MemoryNotFoundError": MemoryNotFoundError,
    "ProviderConfigurationError": ProviderConfigurationError,
    "ProviderCapabilityError": ProviderCapabilityError,
    "ProviderScopeRequiredError": ProviderScopeRequiredError,
    "ProviderUnavailableError": ProviderUnavailableError,
    "ProviderValidationError": ProviderValidationError,
}


def has_scope(*, user_id=None, agent_id=None, run_id=None) -> bool:
    return any(value is not None for value in (user_id, agent_id, run_id))


def validate_search_request(
    *,
    provider_name: str,
    capabilities: ProviderCapabilities,
    user_id=None,
    agent_id=None,
    run_id=None,
    filters=None,
    rerank: bool | None = None,
) -> None:
    # Transport-neutral wording — the same validator runs from the MCP tool
    # dispatcher, the HTTP endpoint, and the CLI, so error messages must not
    # read like CLI help ("--user-id", "--no-rerank"). CLI-facing hints live
    # in argparse definitions.
    if capabilities["requires_scope_for_search"] and not has_scope(user_id=user_id, agent_id=agent_id, run_id=run_id):
        raise ProviderValidationError(
            f"Provider '{provider_name}' requires user_id, agent_id, or run_id for search."
        )
    if filters is not None and not capabilities["supports_filters"]:
        raise ProviderValidationError(f"Provider '{provider_name}' does not support filters for search.")
    if rerank and not capabilities["supports_rerank"]:
        raise ProviderValidationError(
            f"Provider '{provider_name}' does not support rerank. Call memory_search with rerank=false."
        )


def validate_list_request(
    *,
    provider_name: str,
    capabilities: ProviderCapabilities,
    user_id=None,
    agent_id=None,
    run_id=None,
    filters=None,
) -> None:
    if capabilities["requires_scope_for_list"] and not has_scope(user_id=user_id, agent_id=agent_id, run_id=run_id):
        raise ProviderValidationError(
            f"Provider '{provider_name}' requires user_id, agent_id, or run_id for list."
        )
    if filters is not None and not capabilities["supports_filters"]:
        raise ProviderValidationError(f"Provider '{provider_name}' does not support filters for list.")


def build_search_kwargs(source: dict[str, Any], *, default_limit: int = 10) -> dict[str, Any]:
    return {
        "query": source["query"],
        "user_id": source.get("user_id"),
        "agent_id": source.get("agent_id"),
        "run_id": source.get("run_id"),
        "limit": source.get("limit", default_limit),
        "filters": source.get("filters"),
        "threshold": source.get("threshold"),
        "rerank": source.get("rerank", True),
    }


def build_list_kwargs(source: dict[str, Any], *, default_limit: int = 100) -> dict[str, Any]:
    return {
        "user_id": source.get("user_id"),
        "agent_id": source.get("agent_id"),
        "run_id": source.get("run_id"),
        "limit": source.get("limit", default_limit),
        "filters": source.get("filters"),
    }


def validate_and_build_search_kwargs(
    *,
    provider_name: str,
    capabilities: ProviderCapabilities,
    source: dict[str, Any],
    default_limit: int = 10,
) -> dict[str, Any]:
    kwargs = build_search_kwargs(source, default_limit=default_limit)
    # Capability-aware coercion of rerank: the tool schema defaults rerank=true
    # for callers, but a provider that doesn't advertise rerank shouldn't make
    # the default explode. Coerce silently instead of raising.
    if kwargs["rerank"] and not capabilities["supports_rerank"]:
        kwargs["rerank"] = False
    validate_search_request(
        provider_name=provider_name,
        capabilities=capabilities,
        user_id=kwargs["user_id"],
        agent_id=kwargs["agent_id"],
        run_id=kwargs["run_id"],
        filters=kwargs["filters"],
        rerank=kwargs["rerank"],
    )
    return kwargs


def validate_and_build_list_kwargs(
    *,
    provider_name: str,
    capabilities: ProviderCapabilities,
    source: dict[str, Any],
    default_limit: int = 100,
) -> dict[str, Any]:
    kwargs = build_list_kwargs(source, default_limit=default_limit)
    validate_list_request(
        provider_name=provider_name,
        capabilities=capabilities,
        user_id=kwargs["user_id"],
        agent_id=kwargs["agent_id"],
        run_id=kwargs["run_id"],
        filters=kwargs["filters"],
    )
    return kwargs


def execute_transport_operation(
    *,
    use_proxy: bool,
    local_call: Callable[[], Any],
    proxy_call: Callable[[], Any] | None = None,
) -> Any:
    if use_proxy:
        if proxy_call is None:
            raise ProviderValidationError("Proxy call is not configured for this operation.")
        return proxy_call()
    return local_call()


def provider_error_status(exc: ProviderError) -> int:
    if isinstance(exc, MemoryNotFoundError):
        return 404
    if isinstance(exc, (ProviderConfigurationError, ProviderUnavailableError)):
        return 503
    if isinstance(exc, (ProviderValidationError, ProviderScopeRequiredError, ProviderCapabilityError)):
        return 400
    return 500


def provider_error_payload(exc: ProviderError) -> dict[str, Any]:
    return {"error_type": exc.__class__.__name__, "message": str(exc)}


def error_class_for_type(error_type: str, *, status_code: int) -> type[ProviderError]:
    if error_type in ERROR_TYPE_MAP:
        return ERROR_TYPE_MAP[error_type]
    return ProviderUnavailableError if status_code >= 500 else ProviderValidationError


def capability_summary(capabilities: ProviderCapabilities) -> dict[str, str]:
    search_mode = "semantic" if capabilities["supports_semantic_search"] else "text" if capabilities["supports_text_search"] else "none"
    return {
        "search_mode": search_mode,
        "supports_filters": "yes" if capabilities["supports_filters"] else "no",
        "supports_rerank": "yes" if capabilities["supports_rerank"] else "no",
        "supports_scope_inventory": "yes" if capabilities["supports_scope_inventory"] else "no",
        "requires_scope_for_search": "yes" if capabilities["requires_scope_for_search"] else "no",
        "requires_scope_for_list": "yes" if capabilities["requires_scope_for_list"] else "no",
        "supports_owner_process_mode": "yes" if capabilities["supports_owner_process_mode"] else "no",
    }


def mcp_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    structured = payload if isinstance(payload, dict) else {"result": payload}
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=True, indent=2, default=str)}],
        "structuredContent": structured,
        "isError": is_error,
    }
