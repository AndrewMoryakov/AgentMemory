import unittest

from agentmemory_guidance import client_runtime_guidance, guidance_summary_lines, provider_guidance


class AgentMemoryGuidanceTests(unittest.TestCase):
    def test_provider_guidance_warns_when_scope_is_required(self) -> None:
        guidance = provider_guidance(
            "mem0",
            {
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
            },
        )

        messages = [item["message"] for item in guidance]
        self.assertTrue(any("requires scope" in message for message in messages))
        self.assertTrue(any("owner-process mode" in message for message in messages))

    def test_guidance_summary_lines_limits_output(self) -> None:
        lines = guidance_summary_lines(
            "localjson",
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
            },
            limit=1,
        )

        self.assertEqual(len(lines), 1)

    def test_client_runtime_guidance_warns_about_stale_configs_and_scope(self) -> None:
        guidance = client_runtime_guidance(
            "mem0",
            {
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
            },
            [
                {"target": "cursor", "configured": True, "health": "stale_config", "stale_launcher": True},
            ],
            local_server_ok=False,
        )

        messages = [item["message"] for item in guidance]
        self.assertTrue(any("Stale client launcher configuration" in message for message in messages))
        self.assertTrue(any("requires scope" in message for message in messages))
        self.assertTrue(any("local server health check is failing" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
