from __future__ import annotations

from dataclasses import dataclass

from agentmemory.runtime.config import provider_class


@dataclass(frozen=True)
class ProviderCertificationPolicy:
    provider_name: str
    expected_status_code: str
    notes: str = ""


def certification_policy_targets() -> dict[str, ProviderCertificationPolicy]:
    localjson = provider_class("localjson")
    mem0 = provider_class("mem0")
    return {
        "localjson": ProviderCertificationPolicy(
            provider_name=localjson.provider_name,
            expected_status_code=str(localjson.provider_metadata()["expected_certification_status_code"]),
            notes=str(localjson.provider_metadata()["certification_notes"]),
        ),
        "mem0": ProviderCertificationPolicy(
            provider_name=mem0.provider_name,
            expected_status_code=str(mem0.provider_metadata()["expected_certification_status_code"]),
            notes=str(mem0.provider_metadata()["certification_notes"]),
        ),
    }
