from __future__ import annotations

import os
from functools import lru_cache
import importlib.metadata
from threading import Lock
from typing import Any

from mem0 import Memory

from memory_provider import BaseMemoryProvider


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PLACEHOLDER_KEYS = {"paste-your-openrouter-key-here", "YOUR_OPENROUTER_API_KEY"}


class ConfigurationError(RuntimeError):
    pass


def is_configured_api_key(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip()
    return bool(normalized) and normalized not in PLACEHOLDER_KEYS


class Mem0Provider(BaseMemoryProvider):
    provider_name = "mem0"
    display_name = "Mem0"

    @classmethod
    def default_provider_config(cls, *, runtime_dir: str) -> dict[str, Any]:
        return {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": "agentmemory_openrouter",
                    "path": runtime_dir.replace("\\", "/") + "/qdrant",
                    "on_disk": True,
                    "embedding_model_dims": 1536,
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": "google/gemma-4-31b-it",
                    "temperature": 0.1,
                    "max_tokens": 1500,
                    "top_p": 0.1,
                    "openrouter_base_url": OPENROUTER_BASE_URL,
                    "site_url": "https://local.agentmemory",
                    "app_name": "AgentMemory",
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": "google/gemini-embedding-001",
                    "openai_base_url": OPENROUTER_BASE_URL,
                    "embedding_dims": 1536,
                },
            },
            "history_db_path": runtime_dir.replace("\\", "/") + "/history.db",
        }

    @classmethod
    def install_requirements(cls) -> list[str]:
        return ["mem0ai==1.0.10"]

    @classmethod
    def configure_parser(cls, parser) -> None:
        parser.add_argument("--openrouter-api-key", help="Store OPENROUTER_API_KEY in .env")
        parser.add_argument("--llm-model")
        parser.add_argument("--embedding-model")
        parser.add_argument("--embedding-dims", type=int)
        parser.add_argument("--collection-name")
        parser.add_argument("--site-url")
        parser.add_argument("--app-name")

    @classmethod
    def env_updates_from_args(cls, args) -> dict[str, str]:
        updates: dict[str, str] = {}
        if getattr(args, "openrouter_api_key", None):
            updates["OPENROUTER_API_KEY"] = args.openrouter_api_key
        return updates

    @classmethod
    def apply_cli_configuration(cls, *, provider_config: dict[str, Any], args) -> bool:
        changed = False
        if args.llm_model:
            provider_config["llm"]["config"]["model"] = args.llm_model
            changed = True
        if args.embedding_model:
            provider_config["embedder"]["config"]["model"] = args.embedding_model
            changed = True
        if args.embedding_dims is not None:
            provider_config["embedder"]["config"]["embedding_dims"] = args.embedding_dims
            provider_config["vector_store"]["config"]["embedding_model_dims"] = args.embedding_dims
            changed = True
        if args.collection_name:
            provider_config["vector_store"]["config"]["collection_name"] = args.collection_name
            changed = True
        if args.site_url:
            provider_config["llm"]["config"]["site_url"] = args.site_url
            changed = True
        if args.app_name:
            provider_config["llm"]["config"]["app_name"] = args.app_name
            changed = True
        return changed

    def __init__(self, *, runtime_config: dict[str, Any], provider_config: dict[str, Any]) -> None:
        super().__init__(runtime_config=runtime_config, provider_config=provider_config)
        self._memory_lock = Lock()

    def clear_caches(self) -> None:
        self._get_openrouter_api_key.cache_clear()
        self._load_memory.cache_clear()

    @lru_cache(maxsize=1)
    def _get_openrouter_api_key(self) -> str:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not is_configured_api_key(api_key):
            raise ConfigurationError(
                "OPENROUTER_API_KEY is not set. Put it in the shell or in AgentMemory/.env"
            )
        return api_key

    @lru_cache(maxsize=1)
    def _load_memory(self) -> Memory:
        api_key = self._get_openrouter_api_key()
        os.environ.setdefault("OPENAI_API_KEY", api_key)
        os.environ.setdefault("OPENAI_BASE_URL", OPENROUTER_BASE_URL)

        config = dict(self.provider_config)
        embedder = dict(config.get("embedder", {}))
        embedder_config = dict(embedder.get("config", {}))
        embedder_config["api_key"] = api_key
        embedder["config"] = embedder_config
        config["embedder"] = embedder
        return Memory.from_config(config)

    def health(self) -> dict[str, Any]:
        return {"ok": True, **self.runtime_info()}

    def runtime_info(self) -> dict[str, Any]:
        return {
            "llm_model": self.provider_config["llm"]["config"]["model"],
            "embedding_model": self.provider_config["embedder"]["config"]["model"],
            "embedding_dims": self.provider_config["embedder"]["config"]["embedding_dims"],
            "vector_store": self.provider_config["vector_store"]["provider"],
            "openrouter_key_present": is_configured_api_key(os.environ.get("OPENROUTER_API_KEY")),
        }

    def doctor_rows(self) -> list[tuple[str, str]]:
        return [
            ("LLM model", str(self.provider_config["llm"]["config"]["model"])),
            ("Embedding model", str(self.provider_config["embedder"]["config"]["model"])),
            ("Embedding dims", str(self.provider_config["embedder"]["config"]["embedding_dims"])),
            ("Vector store", str(self.provider_config["vector_store"]["provider"])),
        ]

    def dependency_checks(self) -> list[dict[str, str]]:
        checks: list[dict[str, str]] = []
        for requirement in self.install_requirements():
            package_name = requirement.split("==", 1)[0]
            try:
                version = importlib.metadata.version(package_name)
                checks.append({"name": package_name, "ok": "true", "details": version})
            except importlib.metadata.PackageNotFoundError:
                checks.append({"name": package_name, "ok": "false", "details": "not installed"})
        return checks

    def prerequisite_checks(self) -> list[dict[str, str]]:
        return [
            {
                "name": "OPENROUTER_API_KEY",
                "ok": "true" if is_configured_api_key(os.environ.get("OPENROUTER_API_KEY")) else "false",
                "details": "available" if is_configured_api_key(os.environ.get("OPENROUTER_API_KEY")) else "missing",
            }
        ]

    def add_memory(self, *, messages, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None):
        with self._memory_lock:
            memory = self._load_memory()
            return memory.add(
                messages,
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
                metadata=metadata,
                infer=infer,
                memory_type=memory_type,
            )

    def search_memory(self, *, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True):
        with self._memory_lock:
            memory = self._load_memory()
            return memory.search(
                query,
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
                limit=limit,
                filters=filters,
                threshold=threshold,
                rerank=rerank,
            )

    def list_memories(self, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None):
        with self._memory_lock:
            memory = self._load_memory()
            return memory.get_all(
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
                limit=limit,
                filters=filters,
            )

    def get_memory(self, memory_id):
        with self._memory_lock:
            return self._load_memory().get(memory_id)

    def update_memory(self, *, memory_id, data, metadata=None):
        with self._memory_lock:
            return self._load_memory().update(memory_id, data, metadata=metadata)

    def delete_memory(self, *, memory_id):
        with self._memory_lock:
            return self._load_memory().delete(memory_id)
