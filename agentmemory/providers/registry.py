from __future__ import annotations

from dataclasses import dataclass

from agentmemory.providers.base import BaseMemoryProvider, ProviderConfigurationError
from agentmemory.providers.claude_memory import ClaudeMemoryProvider
from agentmemory.providers.localjson import LocalJsonProvider
from agentmemory.providers.mem0 import Mem0Provider


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_class: type[BaseMemoryProvider]

    @property
    def provider_name(self) -> str:
        return self.provider_class.provider_name

    @property
    def metadata(self) -> dict[str, object]:
        return self.provider_class.provider_metadata()


def provider_descriptors() -> dict[str, ProviderDescriptor]:
    providers = (LocalJsonProvider, Mem0Provider, ClaudeMemoryProvider)
    return {provider.provider_name: ProviderDescriptor(provider_class=provider) for provider in providers}


def provider_registry() -> dict[str, type[BaseMemoryProvider]]:
    return {name: descriptor.provider_class for name, descriptor in provider_descriptors().items()}


def provider_class(provider_name: str) -> type[BaseMemoryProvider]:
    registry = provider_registry()
    if provider_name not in registry:
        raise ProviderConfigurationError(f"Unknown memory provider: {provider_name}")
    return registry[provider_name]


def onboarding_provider_names() -> list[str]:
    descriptors = [
        descriptor
        for descriptor in provider_descriptors().values()
        if bool(descriptor.metadata.get("onboarding_enabled", True))
    ]
    descriptors.sort(
        key=lambda descriptor: (
            int(descriptor.metadata.get("onboarding_order") or 100),
            descriptor.provider_name,
        )
    )
    return [descriptor.provider_name for descriptor in descriptors]


def default_onboarding_provider_name() -> str:
    for descriptor in provider_descriptors().values():
        if bool(descriptor.metadata.get("onboarding_default", False)):
            return descriptor.provider_name
    names = onboarding_provider_names()
    if not names:
        raise ProviderConfigurationError("No onboarding-enabled memory providers are registered.")
    return names[0]
