import unittest

from agentmemory.runtime.transport import (
    build_list_kwargs,
    build_search_kwargs,
    capability_summary,
    error_class_for_type,
    execute_transport_operation,
    mcp_result,
    provider_error_payload,
    provider_error_status,
    validate_and_build_list_kwargs,
    validate_and_build_search_kwargs,
    validate_list_request,
    validate_search_request,
)
from agentmemory.providers.base import (
    MemoryNotFoundError,
    ProviderCapabilityError,
    ProviderScopeRequiredError,
    ProviderUnavailableError,
    ProviderValidationError,
)


class AgentMemoryTransportTests(unittest.TestCase):
    def test_build_search_kwargs_applies_defaults(self) -> None:
        self.assertEqual(
            build_search_kwargs({"query": "demo"}),
            {
                "query": "demo",
                "user_id": None,
                "agent_id": None,
                "run_id": None,
                "limit": 10,
                "filters": None,
                "threshold": None,
                "rerank": True,
            },
        )

    def test_build_list_kwargs_applies_defaults(self) -> None:
        self.assertEqual(
            build_list_kwargs({}),
            {
                "user_id": None,
                "agent_id": None,
                "run_id": None,
                "limit": 100,
                "filters": None,
            },
        )

    def test_validate_and_build_search_kwargs_uses_shared_validation(self) -> None:
        with self.assertRaises(ProviderValidationError):
            validate_and_build_search_kwargs(
                provider_name="mem0",
                capabilities={
                    "supports_semantic_search": True,
                    "supports_text_search": False,
                    "supports_filters": True,
                    "supports_metadata_filters": True,
                    "supports_rerank": True,
                    "supports_update": True,
                    "supports_delete": True,
                    "supports_scopeless_list": False,
                    "requires_scope_for_list": True,
                    "requires_scope_for_search": True,
                    "supports_owner_process_mode": True,
                    "supports_scope_inventory": True,
                "supports_pagination": False,
                },
                source={"query": "demo"},
            )

    def test_validate_and_build_list_kwargs_uses_shared_validation(self) -> None:
        with self.assertRaises(ProviderValidationError):
            validate_and_build_list_kwargs(
                provider_name="example",
                capabilities={
                    "supports_semantic_search": False,
                    "supports_text_search": True,
                    "supports_filters": False,
                    "supports_metadata_filters": False,
                    "supports_rerank": False,
                    "supports_update": True,
                    "supports_delete": True,
                    "supports_scopeless_list": True,
                    "requires_scope_for_list": False,
                    "requires_scope_for_search": False,
                    "supports_owner_process_mode": False,
                    "supports_scope_inventory": True,
                "supports_pagination": False,
                },
                source={"filters": {"topic": "docs"}},
            )

    def test_validate_search_request_requires_scope_when_declared(self) -> None:
        with self.assertRaises(ProviderValidationError):
            validate_search_request(
                provider_name="mem0",
                capabilities={
                    "supports_semantic_search": True,
                    "supports_text_search": False,
                    "supports_filters": True,
                    "supports_metadata_filters": True,
                    "supports_rerank": True,
                    "supports_update": True,
                    "supports_delete": True,
                    "supports_scopeless_list": False,
                    "requires_scope_for_list": True,
                    "requires_scope_for_search": True,
                    "supports_owner_process_mode": True,
                    "supports_scope_inventory": True,
                "supports_pagination": False,
                },
                rerank=True,
            )

    def test_execute_transport_operation_prefers_local_when_proxy_disabled(self) -> None:
        self.assertEqual(
            execute_transport_operation(
                use_proxy=False,
                local_call=lambda: "local",
                proxy_call=lambda: "proxy",
            ),
            "local",
        )

    def test_execute_transport_operation_uses_proxy_when_enabled(self) -> None:
        self.assertEqual(
            execute_transport_operation(
                use_proxy=True,
                local_call=lambda: "local",
                proxy_call=lambda: "proxy",
            ),
            "proxy",
        )

    def test_execute_transport_operation_rejects_missing_proxy_call(self) -> None:
        with self.assertRaises(ProviderValidationError):
            execute_transport_operation(
                use_proxy=True,
                local_call=lambda: "local",
            )

    def test_validate_search_request_rejects_unsupported_rerank(self) -> None:
        with self.assertRaises(ProviderValidationError):
            validate_search_request(
                provider_name="localjson",
                capabilities={
                    "supports_semantic_search": False,
                    "supports_text_search": True,
                    "supports_filters": True,
                    "supports_metadata_filters": True,
                    "supports_rerank": False,
                    "supports_update": True,
                    "supports_delete": True,
                    "supports_scopeless_list": True,
                    "requires_scope_for_list": False,
                    "requires_scope_for_search": False,
                    "supports_owner_process_mode": False,
                    "supports_scope_inventory": True,
                "supports_pagination": False,
                },
                user_id="u1",
                rerank=True,
            )

    def test_validate_list_request_rejects_unsupported_filters(self) -> None:
        with self.assertRaises(ProviderValidationError):
            validate_list_request(
                provider_name="example",
                capabilities={
                    "supports_semantic_search": False,
                    "supports_text_search": True,
                    "supports_filters": False,
                    "supports_metadata_filters": False,
                    "supports_rerank": False,
                    "supports_update": True,
                    "supports_delete": True,
                    "supports_scopeless_list": True,
                    "requires_scope_for_list": False,
                    "requires_scope_for_search": False,
                    "supports_owner_process_mode": False,
                    "supports_scope_inventory": True,
                "supports_pagination": False,
                },
                filters={"topic": "docs"},
            )

    def test_provider_error_status_and_payload_are_shared(self) -> None:
        exc = ProviderCapabilityError("unsupported rerank")

        self.assertEqual(provider_error_status(exc), 400)
        self.assertEqual(
            provider_error_payload(exc),
            {"error_type": "ProviderCapabilityError", "message": "unsupported rerank"},
        )

    def test_error_class_for_type_uses_status_code_fallback(self) -> None:
        self.assertIs(error_class_for_type("MemoryNotFoundError", status_code=404), MemoryNotFoundError)
        self.assertIs(error_class_for_type("", status_code=503), ProviderUnavailableError)
        self.assertIs(error_class_for_type("", status_code=400), ProviderValidationError)

    def test_capability_summary_renders_human_readable_flags(self) -> None:
        summary = capability_summary(
            {
                "supports_semantic_search": False,
                "supports_text_search": True,
                "supports_filters": True,
                "supports_metadata_filters": True,
                "supports_rerank": False,
                "supports_update": True,
                "supports_delete": True,
                "supports_scopeless_list": True,
                "requires_scope_for_list": False,
                "requires_scope_for_search": False,
                "supports_owner_process_mode": False,
                "supports_scope_inventory": True,
                "supports_pagination": False,
            }
        )

        self.assertEqual(summary["search_mode"], "text")
        self.assertEqual(summary["supports_filters"], "yes")
        self.assertEqual(summary["supports_rerank"], "no")
        self.assertEqual(summary["supports_scope_inventory"], "yes")
        self.assertEqual(summary["supports_pagination"], "no")

    def test_mcp_result_uses_shared_shape_for_success_and_errors(self) -> None:
        success = mcp_result({"value": 1})
        failure = mcp_result({"error_type": "ProviderValidationError"}, is_error=True)

        self.assertEqual(success["structuredContent"], {"value": 1})
        self.assertFalse(success["isError"])
        self.assertEqual(failure["structuredContent"]["error_type"], "ProviderValidationError")
        self.assertTrue(failure["isError"])


if __name__ == "__main__":
    unittest.main()
