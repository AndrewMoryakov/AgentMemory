from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypedDict


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


class BaseMemoryProvider(ABC):
    provider_name = "base"
    display_name = "Base"
    summary = "Base memory provider."
    certification_status = "experimental"
    expected_certification_status_code: str | None = None
    certification_notes = ""

    def __init__(self, *, runtime_config: dict[str, Any], provider_config: dict[str, Any]) -> None:
        self.runtime_config = runtime_config
        self.provider_config = provider_config

    @classmethod
    def provider_metadata(cls) -> dict[str, Any]:
        return {
            "provider_name": cls.provider_name,
            "display_name": cls.display_name,
            "summary": cls.summary,
            "certification_status": cls.certification_status,
            "expected_certification_status_code": cls.expected_certification_status_code,
            "certification_notes": cls.certification_notes,
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
    @abstractmethod
    def apply_cli_configuration(cls, *, provider_config: dict[str, Any], args) -> bool:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

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

    @abstractmethod
    def list_memories(self, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None) -> list[MemoryRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_memory(self, memory_id) -> MemoryRecord:
        raise NotImplementedError

    @abstractmethod
    def update_memory(self, *, memory_id, data, metadata=None) -> MemoryRecord:
        raise NotImplementedError

    @abstractmethod
    def delete_memory(self, *, memory_id) -> DeleteResult:
        raise NotImplementedError

    @abstractmethod
    def list_scopes(self, *, limit: int = 200, kind: str | None = None, query: str | None = None) -> ScopeInventory:
        raise NotImplementedError
