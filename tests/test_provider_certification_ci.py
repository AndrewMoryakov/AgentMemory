import io
import json
import sys
import unittest
from unittest import mock

import provider_certification_ci
import provider_certification_policy
from provider_certify import CertificationAssessment


def make_assessment(*, provider_name: str, status_code: str, verdict: str = "certified") -> CertificationAssessment:
    unmet = () if status_code.startswith("certified") or status_code == "test_only" else ("synthetic failure",)
    skipped = 1 if status_code == "certified_with_skips" else 0
    return CertificationAssessment(
        provider_name=provider_name,
        registry_status="certified",
        checklist_present=True,
        has_harness=True,
        harness_classes=(f"{provider_name}.Harness",),
        test_modules=(),
        tests_ran=True,
        tests_passed=not unmet,
        test_summary={"total": 5, "failures": 0 if not unmet else 1, "errors": 0, "skipped": skipped, "successful": not unmet},
        test_output="",
        unmet_requirements=unmet,
    )


class ProviderCertificationCiTests(unittest.TestCase):
    def test_selected_policy_targets_returns_expected_defaults(self) -> None:
        targets = provider_certification_ci.selected_policy_targets()

        self.assertEqual([target.provider_name for target in targets], ["localjson", "mem0"])

    def test_policy_targets_use_provider_metadata(self) -> None:
        targets = provider_certification_policy.certification_policy_targets()

        self.assertEqual(targets["localjson"].expected_status_code, "certified")
        self.assertEqual(targets["mem0"].notes, "Mem0 is expected to certify with one skipped negative-path harness case.")

    def test_run_policy_check_returns_success_when_status_codes_match(self) -> None:
        assessments = {
            "localjson": make_assessment(provider_name="localjson", status_code="certified"),
            "mem0": make_assessment(provider_name="mem0", status_code="certified_with_skips"),
        }
        with mock.patch.object(provider_certification_ci, "assess_provider", side_effect=lambda name, run_tests: assessments[name]):
            ok, payload = provider_certification_ci.run_policy_check()

        self.assertTrue(ok)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["results"]), 2)
        self.assertTrue(all(item["ok"] for item in payload["results"]))

    def test_run_policy_check_returns_failure_when_status_code_mismatches(self) -> None:
        assessments = {
            "localjson": make_assessment(provider_name="localjson", status_code="certified"),
            "mem0": make_assessment(provider_name="mem0", status_code="certified"),
        }
        with mock.patch.object(provider_certification_ci, "assess_provider", side_effect=lambda name, run_tests: assessments[name]):
            ok, payload = provider_certification_ci.run_policy_check()

        self.assertFalse(ok)
        self.assertFalse(payload["ok"])
        mismatch = next(item for item in payload["results"] if item["provider_name"] == "mem0")
        self.assertFalse(mismatch["ok"])
        self.assertEqual(mismatch["expected_status_code"], "certified_with_skips")
        self.assertEqual(mismatch["actual_status_code"], "certified")

    def test_main_json_outputs_payload(self) -> None:
        original_argv = sys.argv
        original_stdout = sys.stdout
        buffer = io.StringIO()
        fake_payload = {"ok": True, "results": [{"provider_name": "localjson", "ok": True}]}
        try:
            sys.argv = ["provider_certification_ci.py", "--json"]
            sys.stdout = buffer
            with mock.patch.object(provider_certification_ci, "run_policy_check", return_value=(True, fake_payload)):
                rc = provider_certification_ci.main()
        finally:
            sys.argv = original_argv
            sys.stdout = original_stdout

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buffer.getvalue()), fake_payload)

    def test_main_text_exits_non_zero_on_failure(self) -> None:
        original_argv = sys.argv
        original_stdout = sys.stdout
        buffer = io.StringIO()
        fake_payload = {"ok": False, "results": [{"provider_name": "mem0", "ok": False, "expected_status_code": "certified_with_skips", "actual_status_code": "certified"}]}
        try:
            sys.argv = ["provider_certification_ci.py"]
            sys.stdout = buffer
            with mock.patch.object(provider_certification_ci, "run_policy_check", return_value=(False, fake_payload)):
                rc = provider_certification_ci.main()
        finally:
            sys.argv = original_argv
            sys.stdout = original_stdout

        self.assertEqual(rc, 1)
        self.assertIn("Overall: failed", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
