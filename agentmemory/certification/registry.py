from __future__ import annotations

from dataclasses import dataclass

from agentmemory.providers.registry import provider_descriptors


@dataclass(frozen=True)
class ProviderCertificationTarget:
    provider_name: str
    status: str
    description: str
    harness_classes: tuple[str, ...]
    related_test_modules: tuple[str, ...]


def certification_targets() -> dict[str, ProviderCertificationTarget]:
    targets: dict[str, ProviderCertificationTarget] = {}
    for descriptor in provider_descriptors().values():
        metadata = descriptor.metadata
        targets[descriptor.provider_name] = ProviderCertificationTarget(
            provider_name=descriptor.provider_name,
            status=str(metadata["certification_status"]),
            description=str(metadata["summary"]),
            harness_classes=tuple(str(item) for item in metadata.get("certification_harness_classes", ())),
            related_test_modules=tuple(str(item) for item in metadata.get("certification_related_test_modules", ())),
        )
    targets.update(
        {
        "inmemory-contract": ProviderCertificationTarget(
            provider_name="inmemory-contract",
            status="test-only",
            description="Test-only provider used to prove the reusable contract harness is backend-agnostic.",
            harness_classes=("test_provider_contract_harness_fake.InMemoryContractProviderHarnessTests",),
            related_test_modules=("test_provider_contract_harness_fake",),
        ),
        }
    )
    return targets
