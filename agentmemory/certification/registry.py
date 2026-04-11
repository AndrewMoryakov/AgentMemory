from __future__ import annotations

from dataclasses import dataclass

from agentmemory.runtime.config import provider_class


@dataclass(frozen=True)
class ProviderCertificationTarget:
    provider_name: str
    status: str
    description: str
    harness_classes: tuple[str, ...]
    related_test_modules: tuple[str, ...]


def certification_targets() -> dict[str, ProviderCertificationTarget]:
    localjson = provider_class("localjson")
    mem0 = provider_class("mem0")
    return {
        "localjson": ProviderCertificationTarget(
            provider_name=localjson.provider_name,
            status=str(localjson.provider_metadata()["certification_status"]),
            description=str(localjson.provider_metadata()["summary"]),
            harness_classes=("test_localjson_provider.LocalJsonProviderTests",),
            related_test_modules=(
                "test_localjson_provider",
                "test_provider_contract_v1",
                "test_agentmemory_runtime",
                "test_agentmemory_http_client",
                "test_agentmemory_mcp_server",
                "test_agentmemory_admin",
                "test_agentmemory_core",
            ),
        ),
        "mem0": ProviderCertificationTarget(
            provider_name=mem0.provider_name,
            status=str(mem0.provider_metadata()["certification_status"]),
            description=str(mem0.provider_metadata()["summary"]),
            harness_classes=("test_mem0_provider.Mem0ProviderHarnessTests",),
            related_test_modules=(
                "test_mem0_provider",
                "test_provider_contract_v1",
                "test_agentmemory_runtime",
                "test_agentmemory_http_client",
                "test_agentmemory_mcp_server",
                "test_agentmemory_core",
            ),
        ),
        "inmemory-contract": ProviderCertificationTarget(
            provider_name="inmemory-contract",
            status="test-only",
            description="Test-only provider used to prove the reusable contract harness is backend-agnostic.",
            harness_classes=("test_provider_contract_harness_fake.InMemoryContractProviderHarnessTests",),
            related_test_modules=("test_provider_contract_harness_fake",),
        ),
    }
