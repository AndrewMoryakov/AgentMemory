from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseMemoryProvider(ABC):
    provider_name = "base"
    display_name = "Base"

    def __init__(self, *, runtime_config: dict[str, Any], provider_config: dict[str, Any]) -> None:
        self.runtime_config = runtime_config
        self.provider_config = provider_config

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
    def add_memory(self, *, messages, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None):
        raise NotImplementedError

    @abstractmethod
    def search_memory(self, *, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True):
        raise NotImplementedError

    @abstractmethod
    def list_memories(self, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None):
        raise NotImplementedError

    @abstractmethod
    def get_memory(self, memory_id):
        raise NotImplementedError

    @abstractmethod
    def update_memory(self, *, memory_id, data, metadata=None):
        raise NotImplementedError

    @abstractmethod
    def delete_memory(self, *, memory_id):
        raise NotImplementedError
