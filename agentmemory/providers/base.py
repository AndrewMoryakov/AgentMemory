from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal, TypedDict


class ProviderError(RuntimeError):
    pass


class ProviderConfigurationError(ProviderError):
    pass


class ProviderCapabilityError(ProviderError):
    pass


class ProviderScopeRequiredError(ProviderError):
    pass


class MemoryNotFoundError(ProviderError):
    pass


class ProviderUnavailableError(ProviderError):
    pass


class ProviderValidationError(ProviderError):
    pass


def provider_error_payload(exc: ProviderError) -> dict[str, Any]:
    return {
        "error_type": exc.__class__.__name__,
        "message": str(exc),
    }


class ProviderCapabilities(TypedDict):
    supports_semantic_search: bool
    supports_text_search: bool
    supports_filters: bool
    supports_metadata_filters: bool
    supports_rerank: bool
    supports_update: bool
    supports_delete: bool
    supports_scopeless_list: bool
    requires_scope_for_list: bool
    requires_scope_for_search: bool
    supports_owner_process_mode: bool
    supports_scope_inventory: bool
    supports_pagination: bool


class MemoryPage(TypedDict):
    provider: str
    items: list[MemoryRecord]
    next_cursor: str | None
    pagination_supported: bool


class ProviderRuntimePolicy(TypedDict):
    transport_mode: Literal["direct", "owner_process_proxy", "remote_only"]


class ProviderContract(TypedDict):
    contract_version: Literal["v2"]
    record_shape: Literal["memory_record_v1"]
    scope_kinds: list[Literal["user", "agent", "run"]]
    consistency: Literal["immediate", "eventual"]
    write_visibility: Literal["immediate", "owner_process_proxy", "eventual"]
    update_semantics: Literal["replace"]
    delete_semantics: Literal["hard_delete", "provider_defined"]
    filter_semantics: Literal["record_and_metadata", "provider_defined"]
    metadata_value_policy: Literal["json_object"]
    supports_background_ingest: bool
    supports_remote_transport: bool


class MemoryRecord(TypedDict, total=False):
    id: str
    memory: str
    metadata: dict[str, Any]
    user_id: str | None
    agent_id: str | None
    run_id: str | None
    memory_type: str | None
    created_at: str | None
    updated_at: str | None
    provider: str
    score: float
    raw: dict[str, Any] | list[Any] | str | None


class DeleteResult(TypedDict):
    id: str
    deleted: bool
    provider: str


class ScopeInventoryItem(TypedDict):
    kind: str
    value: str
    count: int
    last_seen_at: str | None


class ScopeInventory(TypedDict):
    provider: str
    items: list[ScopeInventoryItem]
    totals: dict[str, int]


class ScopeInventoryPage(TypedDict):
    provider: str
    items: list[ScopeInventoryItem]
    totals: dict[str, int]
    next_cursor: str | None
    pagination_supported: bool


class BaseMemoryProvider(ABC):
    provider_name = "base"
    display_name = "Base"
    summary = "Base memory provider."
    certification_status = "experimental"
    expected_certification_status_code: str | None = None
    certification_notes = ""
    certification_harness_classes: tuple[str, ...] = ()
    certification_related_test_modules: tuple[str, ...] = ()
    certification_policy_enabled = False
    onboarding_enabled = True
    onboarding_default = False
    onboarding_order = 100

    def __init__(self, *, runtime_config: dict[str, Any], provider_config: dict[str, Any]) -> None:
        self.runtime_config = runtime_config
        self.provider_config = provider_config

    @property
    def runtime_dir(self) -> str:
        return str(self.runtime_config.get("runtime_dir", ""))

    @classmethod
    def provider_metadata(cls) -> dict[str, Any]:
        return {
            "provider_name": cls.provider_name,
            "display_name": cls.display_name,
            "summary": cls.summary,
            "certification_status": cls.certification_status,
            "expected_certification_status_code": cls.expected_certification_status_code,
            "certification_notes": cls.certification_notes,
            "certification_harness_classes": cls.certification_harness_classes,
            "certification_related_test_modules": cls.certification_related_test_modules,
            "certification_policy_enabled": cls.certification_policy_enabled,
            "onboarding_enabled": cls.onboarding_enabled,
            "onboarding_default": cls.onboarding_default,
            "onboarding_order": cls.onboarding_order,
        }

    @classmethod
    @abstractmethod
    def default_provider_config(cls, *, runtime_dir: str) -> dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def install_requirements(cls) -> list[str]:
        return []

    @classmethod
    def configure_parser(cls, parser) -> None:
        return None

    @classmethod
    def env_updates_from_args(cls, args) -> dict[str, str]:
        return {}

    @classmethod
    def onboarding_configuration(cls, *, prompt) -> tuple[list[str], str | None]:
        return [], None

    @classmethod
    @abstractmethod
    def apply_cli_configuration(cls, *, provider_config: dict[str, Any], args) -> bool:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

    @abstractmethod
    def runtime_policy(self) -> ProviderRuntimePolicy:
        raise NotImplementedError

    def provider_contract(self) -> ProviderContract:
        runtime_policy = self.runtime_policy()
        # Default advertises what callers *observe* (immediate visibility after
        # the provider call returns). Providers with genuinely deferred
        # visibility must override and return "eventual" or
        # "owner_process_proxy" explicitly — the base must not emit a
        # non-committal sentinel just because the transport happens to proxy.
        return {
            "contract_version": "v2",
            "record_shape": "memory_record_v1",
            "scope_kinds": ["user", "agent", "run"],
            "consistency": "immediate",
            "write_visibility": "immediate",
            "update_semantics": "replace",
            "delete_semantics": "hard_delete",
            "filter_semantics": "record_and_metadata",
            "metadata_value_policy": "json_object",
            "supports_background_ingest": False,
            "supports_remote_transport": runtime_policy["transport_mode"] == "remote_only",
        }

    @abstractmethod
    def doctor_rows(self) -> list[tuple[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def dependency_checks(self) -> list[dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def prerequisite_checks(self) -> list[dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def runtime_info(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def add_memory(self, *, messages, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None) -> MemoryRecord:
        raise NotImplementedError

    @abstractmethod
    def search_memory(self, *, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True) -> list[MemoryRecord]:
        raise NotImplementedError

    def search_memory_page(
        self,
        *,
        query,
        user_id=None,
        agent_id=None,
        run_id=None,
        limit=10,
        cursor=None,
        filters=None,
        threshold=None,
        rerank=True,
    ) -> MemoryPage:
        if cursor is not None:
            raise ProviderCapabilityError(f"{self.display_name} does not support paginated search cursors.")
        return {
            "provider": self.provider_name,
            "items": self.search_memory(
                query=query,
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
                limit=limit,
                filters=filters,
                threshold=threshold,
                rerank=rerank,
            ),
            "next_cursor": None,
            "pagination_supported": False,
        }

    @abstractmethod
    def list_memories(self, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None) -> list[MemoryRecord]:
        raise NotImplementedError

    def list_memories_page(self, *, user_id=None, agent_id=None, run_id=None, limit=100, cursor=None, filters=None) -> MemoryPage:
        if cursor is not None:
            raise ProviderCapabilityError(f"{self.display_name} does not support paginated list cursors.")
        return {
            "provider": self.provider_name,
            "items": self.list_memories(
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
                limit=limit,
                filters=filters,
            ),
            "next_cursor": None,
            "pagination_supported": False,
        }

    @abstractmethod
    def get_memory(self, memory_id) -> MemoryRecord:
        raise NotImplementedError

    def update_memory(self, *, memory_id, data, metadata=None) -> MemoryRecord:
        raise ProviderCapabilityError(f"{self.display_name} does not support memory update.")

    def delete_memory(self, *, memory_id) -> DeleteResult:
        raise ProviderCapabilityError(f"{self.display_name} does not support memory delete.")

    @abstractmethod
    def list_scopes(self, *, limit: int = 200, kind: str | None = None, query: str | None = None) -> ScopeInventory:
        raise NotImplementedError

    def list_scopes_page(
        self,
        *,
        limit: int = 200,
        cursor: str | None = None,
        kind: str | None = None,
        query: str | None = None,
    ) -> ScopeInventoryPage:
        if cursor is not None:
            raise ProviderCapabilityError(f"{self.display_name} does not support paginated scope inventory cursors.")
        inventory = self.list_scopes(limit=limit, kind=kind, query=query)
        return {
            "provider": inventory["provider"],
            "items": inventory["items"],
            "totals": inventory["totals"],
            "next_cursor": None,
            "pagination_supported": False,
        }

    def iter_scope_registry_seed_records(self) -> list[MemoryRecord]:
        raise ProviderCapabilityError(f"{self.display_name} does not support scope-registry rebuild.")
