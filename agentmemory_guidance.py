from __future__ import annotations

from typing import Any

from memory_provider import ProviderCapabilities


def provider_guidance(provider_name: str, capabilities: ProviderCapabilities) -> list[dict[str, str]]:
    guidance: list[dict[str, str]] = []

    if capabilities.get("requires_scope_for_search") or capabilities.get("requires_scope_for_list"):
        scopes = []
        if capabilities.get("requires_scope_for_search"):
            scopes.append("search")
        if capabilities.get("requires_scope_for_list"):
            scopes.append("list")
        guidance.append(
            {
                "level": "warn",
                "message": (
                    f"Provider '{provider_name}' requires scope for {' and '.join(scopes)}. "
                    "Pass user_id, agent_id, or run_id in clients and scripts."
                ),
            }
        )

    if not capabilities.get("supports_scopeless_list", True):
        guidance.append(
            {
                "level": "warn",
                "message": (
                    f"Provider '{provider_name}' does not support scopeless browsing. "
                    "Use scoped list queries for exploration and diagnostics."
                ),
            }
        )

    if capabilities.get("supports_owner_process_mode"):
        guidance.append(
            {
                "level": "info",
                "message": (
                    f"Provider '{provider_name}' supports owner-process mode. "
                    "Prefer the local API/MCP runtime for multi-client shared workflows."
                ),
            }
        )

    if not capabilities.get("supports_rerank", True):
        guidance.append(
            {
                "level": "info",
                "message": (
                    f"Provider '{provider_name}' does not support rerank. "
                    "Disable rerank in search clients to avoid avoidable validation errors."
                ),
            }
        )

    if capabilities.get("supports_semantic_search"):
        guidance.append(
            {
                "level": "info",
                "message": f"Provider '{provider_name}' is operating in semantic search mode.",
            }
        )
    elif capabilities.get("supports_text_search"):
        guidance.append(
            {
                "level": "info",
                "message": (
                    f"Provider '{provider_name}' is operating in text search mode. "
                    "Expect keyword matching rather than semantic recall."
                ),
            }
        )
    else:
        guidance.append(
            {
                "level": "warn",
                "message": f"Provider '{provider_name}' does not advertise a search mode.",
            }
        )

    return guidance


def guidance_summary_lines(provider_name: str, capabilities: ProviderCapabilities, *, limit: int = 2) -> tuple[str, ...]:
    return tuple(item["message"] for item in provider_guidance(provider_name, capabilities)[:limit])


def client_runtime_guidance(
    provider_name: str,
    capabilities: ProviderCapabilities,
    results: list[dict[str, str]],
    *,
    local_server_ok: bool | None = None,
) -> list[dict[str, str]]:
    guidance: list[dict[str, str]] = []
    active_targets = [
        item.get("target", "")
        for item in results
        if item.get("connected")
        or item.get("configured")
        or item.get("status") == "updated"
    ]
    stale_targets = [item.get("target", "") for item in results if item.get("health") == "stale_config" or item.get("stale_launcher")]

    if stale_targets:
        guidance.append(
            {
                "level": "warn",
                "message": (
                    "Stale client launcher configuration detected for "
                    + ", ".join(sorted(target for target in stale_targets if target))
                    + ". Reconnect clients to refresh the launcher path."
                ),
            }
        )

    if active_targets and (capabilities.get("requires_scope_for_search") or capabilities.get("requires_scope_for_list")):
        guidance.append(
            {
                "level": "warn",
                "message": (
                    f"Active clients are connected to provider '{provider_name}', which requires scope. "
                    "Use user_id, agent_id, or run_id in client-driven search and list workflows."
                ),
            }
        )

    if active_targets and not capabilities.get("supports_rerank", True):
        guidance.append(
            {
                "level": "info",
                "message": (
                    f"Provider '{provider_name}' does not support rerank. "
                    "Prefer client prompts and scripts that disable rerank explicitly."
                ),
            }
        )

    if active_targets and not capabilities.get("supports_scopeless_list", True):
        guidance.append(
            {
                "level": "info",
                "message": (
                    f"Provider '{provider_name}' does not support scopeless browse. "
                    "Use scoped list/search requests in connected clients."
                ),
            }
        )

    if active_targets and capabilities.get("supports_owner_process_mode") and local_server_ok is False:
        guidance.append(
            {
                "level": "warn",
                "message": (
                    f"Connected clients depend on the shared runtime for provider '{provider_name}', "
                    "but the local server health check is failing. Fix the local runtime before relying on shared memory."
                ),
            }
        )

    return guidance
