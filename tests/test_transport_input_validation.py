import unittest

from agentmemory.runtime.transport import (
    build_list_kwargs,
    build_search_kwargs,
    validate_and_build_search_kwargs,
)
from agentmemory.providers.base import ProviderValidationError


def _localjson_capabilities():
    return {
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
    }


def _mem0_capabilities():
    return {
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
    }


class TransportInputValidationTests(unittest.TestCase):
    def test_build_search_kwargs_rejects_empty_query(self) -> None:
        with self.assertRaises(ProviderValidationError):
            build_search_kwargs({"query": ""})

    def test_build_search_kwargs_rejects_none_query(self) -> None:
        with self.assertRaises(ProviderValidationError):
            build_search_kwargs({"query": None})

    def test_build_search_kwargs_rejects_missing_query(self) -> None:
        with self.assertRaises(ProviderValidationError):
            build_search_kwargs({})

    def test_build_search_kwargs_rejects_whitespace_only_query(self) -> None:
        with self.assertRaises(ProviderValidationError):
            build_search_kwargs({"query": "   "})

    def test_build_search_kwargs_rejects_non_string_query(self) -> None:
        with self.assertRaises(ProviderValidationError):
            build_search_kwargs({"query": 123})

    def test_build_search_kwargs_rejects_non_dict_filters(self) -> None:
        with self.assertRaises(ProviderValidationError):
            build_search_kwargs({"query": "test", "filters": "bad"})

    def test_build_search_kwargs_rejects_list_filters(self) -> None:
        with self.assertRaises(ProviderValidationError):
            build_search_kwargs({"query": "test", "filters": ["a", "b"]})

    def test_build_search_kwargs_accepts_dict_filters(self) -> None:
        result = build_search_kwargs({"query": "test", "filters": {"topic": "docs"}})
        self.assertEqual(result["filters"], {"topic": "docs"})

    def test_build_search_kwargs_accepts_none_filters(self) -> None:
        result = build_search_kwargs({"query": "test", "filters": None})
        self.assertIsNone(result["filters"])

    def test_build_search_kwargs_returns_rerank_none_by_default(self) -> None:
        result = build_search_kwargs({"query": "test"})
        self.assertIsNone(result["rerank"])

    def test_build_search_kwargs_preserves_explicit_rerank(self) -> None:
        result = build_search_kwargs({"query": "test", "rerank": True})
        self.assertTrue(result["rerank"])

    def test_build_list_kwargs_rejects_non_dict_filters(self) -> None:
        with self.assertRaises(ProviderValidationError):
            build_list_kwargs({"filters": "bad"})

    def test_build_list_kwargs_accepts_valid_input(self) -> None:
        result = build_list_kwargs({"user_id": "u1", "filters": {"k": "v"}})
        self.assertEqual(result["user_id"], "u1")
        self.assertEqual(result["filters"], {"k": "v"})

    def test_validate_and_build_search_sets_rerank_true_for_supporting_provider(self) -> None:
        result = validate_and_build_search_kwargs(
            provider_name="mem0",
            capabilities=_mem0_capabilities(),
            source={"query": "test", "user_id": "u1"},
        )
        self.assertTrue(result["rerank"])

    def test_validate_and_build_search_sets_rerank_false_for_non_supporting_provider(self) -> None:
        result = validate_and_build_search_kwargs(
            provider_name="localjson",
            capabilities=_localjson_capabilities(),
            source={"query": "test"},
        )
        self.assertFalse(result["rerank"])

    def test_validate_and_build_search_keeps_explicit_rerank_true_if_supported(self) -> None:
        result = validate_and_build_search_kwargs(
            provider_name="mem0",
            capabilities=_mem0_capabilities(),
            source={"query": "test", "rerank": True, "user_id": "u1"},
        )
        self.assertTrue(result["rerank"])

    def test_validate_and_build_search_rejects_explicit_rerank_true_if_not_supported(self) -> None:
        with self.assertRaises(ProviderValidationError):
            validate_and_build_search_kwargs(
                provider_name="localjson",
                capabilities=_localjson_capabilities(),
                source={"query": "test", "rerank": True},
            )

    def test_validate_and_build_search_allows_explicit_rerank_false(self) -> None:
        result = validate_and_build_search_kwargs(
            provider_name="localjson",
            capabilities=_localjson_capabilities(),
            source={"query": "test", "rerank": False},
        )
        self.assertFalse(result["rerank"])


if __name__ == "__main__":
    unittest.main()
