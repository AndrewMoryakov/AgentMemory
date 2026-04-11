from __future__ import annotations

import argparse
import json

from agentmemory.certification.policy import ProviderCertificationPolicy, certification_policy_targets
from agentmemory.certification.certify import assess_provider


def selected_policy_targets(provider_names: list[str] | None = None) -> list[ProviderCertificationPolicy]:
    targets = certification_policy_targets()
    if not provider_names:
        return [targets[name] for name in sorted(targets)]
    missing = [name for name in provider_names if name not in targets]
    if missing:
        raise KeyError(", ".join(sorted(missing)))
    return [targets[name] for name in provider_names]


def run_policy_check(provider_names: list[str] | None = None) -> tuple[bool, dict[str, object]]:
    results: list[dict[str, object]] = []
    overall_ok = True
    for policy in selected_policy_targets(provider_names):
        assessment = assess_provider(policy.provider_name, run_tests=True)
        ok = assessment.status_code == policy.expected_status_code
        overall_ok = overall_ok and ok
        results.append(
            {
                "provider_name": policy.provider_name,
                "expected_status_code": policy.expected_status_code,
                "actual_status_code": assessment.status_code,
                "verdict": assessment.verdict,
                "ok": ok,
                "test_summary": assessment.test_summary,
                "unmet_requirements": list(assessment.unmet_requirements),
                "notes": policy.notes,
            }
        )
    return overall_ok, {"ok": overall_ok, "results": results}


def print_text_report(payload: dict[str, object]) -> None:
    print("Provider certification policy check")
    for item in payload["results"]:  # type: ignore[index]
        row = item  # type: ignore[assignment]
        state = "ok" if row["ok"] else "mismatch"
        print(
            f"- {row['provider_name']}: {state} "
            f"(expected={row['expected_status_code']}, actual={row['actual_status_code']})"
        )
    print(f"Overall: {'ok' if payload['ok'] else 'failed'}")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="provider-certify-ci",
        description="Run the AgentMemory provider certification policy checks for CI or local validation.",
    )
    parser.add_argument(
        "--provider",
        action="append",
        dest="providers",
        help="Limit the policy check to one or more provider names.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    try:
        ok, payload = run_policy_check(args.providers)
    except KeyError as exc:
        parser.error(f"unknown provider policy target: {exc}")

    if args.json:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    else:
        print_text_report(payload)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
