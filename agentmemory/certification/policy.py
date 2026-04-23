from __future__ import annotations

from dataclasses import dataclass

from agentmemory.providers.registry import provider_descriptors


@dataclass(frozen=True)
class ProviderCertificationPolicy:
    provider_name: str
    expected_status_code: str
    notes: str = ""


def certification_policy_targets() -> dict[str, ProviderCertificationPolicy]:
    targets: dict[str, ProviderCertificationPolicy] = {}
    for descriptor in provider_descriptors().values():
        metadata = descriptor.metadata
        if not bool(metadata.get("certification_policy_enabled", False)):
            continue
        targets[descriptor.provider_name] = ProviderCertificationPolicy(
            provider_name=descriptor.provider_name,
            expected_status_code=str(metadata["expected_certification_status_code"]),
            notes=str(metadata["certification_notes"]),
        )
    return targets
