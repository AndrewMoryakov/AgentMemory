import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import provider_certify
import provider_certification_registry


class ProviderCertifyTests(unittest.TestCase):
    def test_get_target_returns_registered_provider(self) -> None:
        target = provider_certify.get_target("localjson")

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.provider_name, "localjson")
        self.assertEqual(target.status, "certified")

    def test_registry_uses_provider_metadata_for_runtime_providers(self) -> None:
        targets = provider_certification_registry.certification_targets()

        self.assertEqual(targets["localjson"].description, "Built-in local JSON provider used for contract validation and local demos.")
        self.assertEqual(targets["mem0"].status, "certified")

    def test_listed_test_module_paths_uses_registry(self) -> None:
        target = provider_certify.get_target("localjson")
        assert target is not None

        paths = provider_certify.listed_test_module_paths(target)

        self.assertTrue(any(path.name == "test_localjson_provider.py" for path in paths))
        self.assertTrue(any(path.name == "test_provider_contract_v1.py" for path in paths))

    def test_list_targets_prints_registered_targets(self) -> None:
        original_stdout = sys.stdout
        buffer = io.StringIO()
        try:
            sys.stdout = buffer
            rc = provider_certify.list_targets()
        finally:
            sys.stdout = original_stdout

        output = buffer.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("localjson [certified]", output)
        self.assertIn("mem0 [certified]", output)

    def test_list_targets_json_emits_machine_readable_payload(self) -> None:
        original_stdout = sys.stdout
        buffer = io.StringIO()
        try:
            sys.stdout = buffer
            rc = provider_certify.list_targets_json()
        finally:
            sys.stdout = original_stdout

        payload = json.loads(buffer.getvalue())
        self.assertEqual(rc, 0)
        self.assertIn("targets", payload)
        self.assertTrue(any(item["provider_name"] == "localjson" for item in payload["targets"]))

    def test_certification_report_uses_registry_metadata(self) -> None:
        original_stdout = sys.stdout
        buffer = io.StringIO()
        try:
            sys.stdout = buffer
            rc = provider_certify.certification_report("localjson", run_tests=False)
        finally:
            sys.stdout = original_stdout

        output = buffer.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Registry status: certified", output)
        self.assertIn("test_localjson_provider.py", output)
        self.assertIn("Harness consumer: yes", output)
        self.assertIn("Certification verdict: certified", output)
        self.assertIn("Status code: certified", output)
        self.assertIn("Unmet requirements: none", output)

    def test_unregistered_provider_reports_failure_without_harness(self) -> None:
        original_stdout = sys.stdout
        buffer = io.StringIO()
        try:
            sys.stdout = buffer
            rc = provider_certify.certification_report("missing-provider", run_tests=False)
        finally:
            sys.stdout = original_stdout

        output = buffer.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("Registry status: unregistered", output)
        self.assertIn("Certification verdict: not certified", output)
        self.assertIn("Status code: not_certified_unregistered", output)

    def test_certification_report_json_emits_verdict(self) -> None:
        original_stdout = sys.stdout
        buffer = io.StringIO()
        try:
            sys.stdout = buffer
            rc = provider_certify.certification_report_json("localjson", run_tests=False)
        finally:
            sys.stdout = original_stdout

        payload = json.loads(buffer.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(payload["provider_name"], "localjson")
        self.assertEqual(payload["registry_status"], "certified")
        self.assertEqual(payload["verdict"], "certified")
        self.assertEqual(payload["status_code"], "certified")
        self.assertEqual(payload["unmet_requirements"], [])
        self.assertIsNone(payload["test_summary"])

    def test_assess_provider_marks_mem0_certified_after_harness_registration(self) -> None:
        assessment = provider_certify.assess_provider("mem0", run_tests=False)

        self.assertEqual(assessment.registry_status, "certified")
        self.assertEqual(assessment.verdict, "certified")
        self.assertEqual(assessment.status_code, "certified")
        self.assertFalse(assessment.unmet_requirements)

    def test_run_tests_for_provider_captures_stdout_noise(self) -> None:
        fake_path = Path("O:/fake/test_noisy_provider.py")
        fake_suite = unittest.TestSuite()

        class NoisyTest(unittest.TestCase):
            def runTest(self) -> None:
                print("noisy stdout")
                print("noisy stderr", file=sys.stderr)

        fake_suite.addTest(NoisyTest())

        with (
            mock.patch.object(provider_certify, "get_target", return_value=None),
            mock.patch.object(provider_certify, "collect_provider_test_modules", return_value=[fake_path]),
            mock.patch.object(unittest.TestLoader, "discover", return_value=fake_suite),
        ):
            outcome = provider_certify.run_tests_for_provider("noisy-provider")

        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.summary["total"], 1)
        self.assertEqual(outcome.summary["failures"], 0)
        self.assertEqual(outcome.summary["errors"], 0)
        self.assertIn("noisy stdout", outcome.output)
        self.assertIn("noisy stderr", outcome.output)

    def test_certification_report_json_with_run_tests_includes_summary(self) -> None:
        assessment = provider_certify.CertificationAssessment(
            provider_name="mem0",
            registry_status="certified",
            checklist_present=True,
            has_harness=True,
            harness_classes=("test_mem0_provider.Mem0ProviderHarnessTests",),
            test_modules=(Path("O:/fake/test_mem0_provider.py"),),
            tests_ran=True,
            tests_passed=True,
            test_summary={"total": 5, "failures": 0, "errors": 0, "skipped": 1, "successful": True},
            test_output="fake detailed log",
            unmet_requirements=(),
        )
        original_stdout = sys.stdout
        buffer = io.StringIO()
        try:
            sys.stdout = buffer
            with mock.patch.object(provider_certify, "assess_provider", return_value=assessment):
                rc = provider_certify.certification_report_json("mem0", run_tests=True)
        finally:
            sys.stdout = original_stdout

        payload = json.loads(buffer.getvalue())
        self.assertEqual(rc, 0)
        self.assertTrue(payload["tests_ran"])
        self.assertTrue(payload["tests_passed"])
        self.assertIsNotNone(payload["test_summary"])
        self.assertEqual(payload["test_summary"]["total"], 5)
        self.assertTrue(payload["test_summary"]["successful"])
        self.assertEqual(payload["status_code"], "certified_with_skips")

    def test_certification_report_json_summary_only_omits_detailed_log(self) -> None:
        assessment = provider_certify.CertificationAssessment(
            provider_name="mem0",
            registry_status="certified",
            checklist_present=True,
            has_harness=True,
            harness_classes=("test_mem0_provider.Mem0ProviderHarnessTests",),
            test_modules=(Path("O:/fake/test_mem0_provider.py"),),
            tests_ran=True,
            tests_passed=True,
            test_summary={"total": 5, "failures": 0, "errors": 0, "skipped": 1, "successful": True},
            test_output="fake detailed log",
            unmet_requirements=(),
        )
        original_stdout = sys.stdout
        buffer = io.StringIO()
        try:
            sys.stdout = buffer
            with mock.patch.object(provider_certify, "assess_provider", return_value=assessment):
                rc = provider_certify.certification_report_json("mem0", run_tests=True, summary_only=True)
        finally:
            sys.stdout = original_stdout

        payload = json.loads(buffer.getvalue())
        self.assertEqual(rc, 0)
        self.assertTrue(payload["tests_ran"])
        self.assertEqual(payload["test_output"], "")
        self.assertIsNotNone(payload["test_summary"])
        self.assertEqual(payload["status_code"], "certified_with_skips")
