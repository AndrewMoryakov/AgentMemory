from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

from agentmemory.certification.registry import ProviderCertificationTarget, certification_targets
from agentmemory.runtime.config import BASE_DIR

TESTS_DIR = BASE_DIR / "tests"
HARNESS_MODULE = TESTS_DIR / "provider_contract_harness.py"

if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))


@dataclass(frozen=True)
class CertificationAssessment:
    provider_name: str
    registry_status: str
    checklist_present: bool
    has_harness: bool
    harness_classes: tuple[str, ...]
    test_modules: tuple[Path, ...]
    tests_ran: bool
    tests_passed: bool
    test_summary: dict[str, object] | None
    test_output: str
    unmet_requirements: tuple[str, ...]

    @property
    def verdict(self) -> str:
        if self.unmet_requirements:
            return "not certified"
        if self.registry_status == "test-only":
            return "test-only"
        return "certified"

    @property
    def status_code(self) -> str:
        if self.verdict == "test-only":
            return "test_only"
        if self.verdict == "certified":
            if self.tests_ran and self.test_summary and int(self.test_summary.get("skipped", 0)) > 0:
                return "certified_with_skips"
            return "certified"
        unmet = set(self.unmet_requirements)
        if f"registry status is {self.registry_status}" in unmet and self.registry_status == "unregistered":
            return "not_certified_unregistered"
        if "related certification tests did not pass" in unmet:
            return "not_certified_tests_failed"
        if "no reusable provider contract harness consumer is registered" in unmet:
            return "not_certified_missing_harness"
        return "not_certified"

    def to_dict(self, *, include_test_output: bool = True) -> dict[str, object]:
        return {
            "provider_name": self.provider_name,
            "registry_status": self.registry_status,
            "checklist_present": self.checklist_present,
            "has_harness": self.has_harness,
            "harness_classes": list(self.harness_classes),
            "test_modules": [path.name for path in self.test_modules],
            "tests_ran": self.tests_ran,
            "tests_passed": self.tests_passed,
            "test_summary": self.test_summary,
            "test_output": self.test_output if include_test_output else "",
            "unmet_requirements": list(self.unmet_requirements),
            "verdict": self.verdict,
            "status_code": self.status_code,
        }


@dataclass(frozen=True)
class TestRunOutcome:
    ok: bool
    output: str
    summary: dict[str, object]


def test_module_names() -> list[str]:
    names: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        names.append(path.stem)
    return names


def load_module_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def collect_provider_test_modules(provider_name: str) -> list[Path]:
    provider_token = provider_name.lower().replace("-", "_")
    matched: list[Path] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if provider_token in path.stem.lower() or provider_token in text.lower():
            matched.append(path)
    return matched


def has_harness_consumer(provider_name: str) -> tuple[bool, list[str]]:
    provider_token = provider_name.lower().replace("-", "_")
    class_names: list[str] = []
    for path in collect_provider_test_modules(provider_name):
        module_name = f"provider_certify_scan_{path.stem}"
        module = load_module_from_path(module_name, path)
        for name, obj in vars(module).items():
            if not isinstance(obj, type):
                continue
            if "ProviderContractHarness" not in [base.__name__ for base in obj.__mro__[1:]]:
                continue
            source_text = path.read_text(encoding="utf-8").lower()
            if provider_token in source_text:
                class_names.append(f"{path.stem}.{name}")
    return bool(class_names), class_names


def get_target(provider_name: str) -> ProviderCertificationTarget | None:
    return certification_targets().get(provider_name)


def listed_test_module_paths(target: ProviderCertificationTarget) -> list[Path]:
    paths: list[Path] = []
    for module_name in target.related_test_modules:
        path = TESTS_DIR / f"{module_name}.py"
        if path.exists():
            paths.append(path)
    return paths


def run_tests_for_provider(provider_name: str) -> TestRunOutcome:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    target = get_target(provider_name)
    matched_modules = listed_test_module_paths(target) if target is not None else collect_provider_test_modules(provider_name)
    if not matched_modules:
        return TestRunOutcome(
            ok=False,
            output=f"No test modules mention provider '{provider_name}'.",
            summary={"total": 0, "failures": 0, "errors": 0, "skipped": 0, "successful": False},
        )

    for path in matched_modules:
        suite.addTests(loader.discover(str(TESTS_DIR), pattern=path.name))

    stream = io.StringIO()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return TestRunOutcome(
        ok=result.wasSuccessful(),
        output=stream.getvalue(),
        summary={
            "total": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(getattr(result, "skipped", [])),
            "successful": result.wasSuccessful(),
        },
    )


def assess_provider(provider_name: str, *, run_tests: bool) -> CertificationAssessment:
    target = get_target(provider_name)
    provider_tests = listed_test_module_paths(target) if target is not None else collect_provider_test_modules(provider_name)
    has_harness, harness_classes = (
        (bool(target.harness_classes), list(target.harness_classes))
        if target is not None
        else has_harness_consumer(provider_name)
    )
    checklist_present = (BASE_DIR / "PROVIDER_CERTIFICATION.md").exists()
    registry_status = target.status if target is not None else "unregistered"
    tests_passed = False
    test_summary: dict[str, object] | None = None
    test_output = ""
    unmet_requirements: list[str] = []

    if not checklist_present:
        unmet_requirements.append("provider certification checklist is missing")
    if not provider_tests:
        unmet_requirements.append("no related test modules are registered or discovered")
    if not has_harness:
        unmet_requirements.append("no reusable provider contract harness consumer is registered")
    if registry_status in {"unregistered", "provisional"}:
        unmet_requirements.append(f"registry status is {registry_status}")

    if run_tests:
        if provider_tests:
            test_run = run_tests_for_provider(provider_name)
            tests_passed = test_run.ok
            test_summary = test_run.summary
            test_output = test_run.output
            if not tests_passed:
                unmet_requirements.append("related certification tests did not pass")
        else:
            test_output = f"No test modules mention provider '{provider_name}'."
            test_summary = {"total": 0, "failures": 0, "errors": 0, "skipped": 0, "successful": False}
    return CertificationAssessment(
        provider_name=provider_name,
        registry_status=registry_status,
        checklist_present=checklist_present,
        has_harness=has_harness,
        harness_classes=tuple(harness_classes),
        test_modules=tuple(provider_tests),
        tests_ran=run_tests,
        tests_passed=tests_passed,
        test_summary=test_summary,
        test_output=test_output,
        unmet_requirements=tuple(unmet_requirements),
    )


def list_targets() -> int:
    print("Provider certification targets:")
    for provider_name, target in sorted(certification_targets().items()):
        print(f"- {provider_name} [{target.status}]")
        print(f"  {target.description}")
    return 0


def list_targets_json() -> int:
    payload = {
        "targets": [
            {
                "provider_name": provider_name,
                "status": target.status,
                "description": target.description,
                "harness_classes": list(target.harness_classes),
                "related_test_modules": list(target.related_test_modules),
            }
            for provider_name, target in sorted(certification_targets().items())
        ]
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


def certification_report(provider_name: str, *, run_tests: bool, summary_only: bool = False) -> int:
    target = get_target(provider_name)
    assessment = assess_provider(provider_name, run_tests=run_tests)
    checklist_path = BASE_DIR / "PROVIDER_CERTIFICATION.md"

    print(f"Provider certification helper: {provider_name}")
    if target is not None:
        print(f"Registry status: {target.status}")
        print(f"Description: {target.description}")
    else:
        print("Registry status: unregistered")
    print(f"Checklist: {'present' if assessment.checklist_present else 'missing'} ({checklist_path.name})")
    print(f"Matched test modules: {len(assessment.test_modules)}")
    for path in assessment.test_modules:
        print(f"  - {path.name}")
    print(f"Harness consumer: {'yes' if assessment.has_harness else 'no'}")
    for item in assessment.harness_classes:
        print(f"  - {item}")
    print(f"Certification verdict: {assessment.verdict}")
    print(f"Status code: {assessment.status_code}")
    if assessment.unmet_requirements:
        print("Unmet requirements:")
        for item in assessment.unmet_requirements:
            print(f"  - {item}")
    else:
        print("Unmet requirements: none")

    if not run_tests:
        return 0 if not assessment.unmet_requirements else 1

    print()
    if assessment.test_summary is not None:
        summary = assessment.test_summary
        print(
            "Test summary: "
            f"total={summary['total']} "
            f"failures={summary['failures']} "
            f"errors={summary['errors']} "
            f"skipped={summary['skipped']} "
            f"successful={str(summary['successful']).lower()}"
        )
        print()
    if summary_only:
        return 0 if not assessment.unmet_requirements else 1
    print("Relevant test run:")
    print((assessment.test_output or "No relevant tests were run.").rstrip())
    return 0 if not assessment.unmet_requirements else 1


def certification_report_json(provider_name: str, *, run_tests: bool, summary_only: bool = False) -> int:
    assessment = assess_provider(provider_name, run_tests=run_tests)
    target = get_target(provider_name)
    payload = assessment.to_dict(include_test_output=not summary_only)
    payload["description"] = target.description if target is not None else None
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if not assessment.unmet_requirements else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="provider-certify",
        description="Check whether a provider appears to satisfy the AgentMemory provider certification workflow.",
    )
    parser.add_argument("provider", nargs="?", help="Provider name token, for example: localjson or mem0")
    parser.add_argument("--list", action="store_true", help="List known certification targets from the provider certification registry.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output for list or provider report modes.")
    parser.add_argument("--run-tests", action="store_true", help="Also run matching test modules for the provider.")
    parser.add_argument("--summary-only", action="store_true", help="Show only the certification verdict and test summary without the detailed test log.")
    args = parser.parse_args()
    if args.list:
        return list_targets_json() if args.json else list_targets()
    if not args.provider:
        parser.error("provider is required unless --list is used")
    if args.json:
        return certification_report_json(args.provider, run_tests=args.run_tests, summary_only=args.summary_only)
    return certification_report(args.provider, run_tests=args.run_tests, summary_only=args.summary_only)


if __name__ == "__main__":
    raise SystemExit(main())
