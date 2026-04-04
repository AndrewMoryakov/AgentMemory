import os
import unittest

import agentmemory_http_client


class AgentMemoryHttpClientTests(unittest.TestCase):
    def test_should_proxy_to_api_for_mem0_when_not_owner(self) -> None:
        original_active_provider_name = agentmemory_http_client.active_provider_name
        original_owner = os.environ.get(agentmemory_http_client.OWNER_ENV)
        try:
            agentmemory_http_client.active_provider_name = lambda: "mem0"  # type: ignore[assignment]
            os.environ.pop(agentmemory_http_client.OWNER_ENV, None)
            self.assertTrue(agentmemory_http_client.should_proxy_to_api())
        finally:
            agentmemory_http_client.active_provider_name = original_active_provider_name  # type: ignore[assignment]
            if original_owner is None:
                os.environ.pop(agentmemory_http_client.OWNER_ENV, None)
            else:
                os.environ[agentmemory_http_client.OWNER_ENV] = original_owner

    def test_should_not_proxy_when_owner_process(self) -> None:
        original_active_provider_name = agentmemory_http_client.active_provider_name
        original_owner = os.environ.get(agentmemory_http_client.OWNER_ENV)
        try:
            agentmemory_http_client.active_provider_name = lambda: "mem0"  # type: ignore[assignment]
            os.environ[agentmemory_http_client.OWNER_ENV] = "1"
            self.assertFalse(agentmemory_http_client.should_proxy_to_api())
        finally:
            agentmemory_http_client.active_provider_name = original_active_provider_name  # type: ignore[assignment]
            if original_owner is None:
                os.environ.pop(agentmemory_http_client.OWNER_ENV, None)
            else:
                os.environ[agentmemory_http_client.OWNER_ENV] = original_owner

    def test_should_not_proxy_for_non_mem0_provider(self) -> None:
        original_active_provider_name = agentmemory_http_client.active_provider_name
        try:
            agentmemory_http_client.active_provider_name = lambda: "localjson"  # type: ignore[assignment]
            self.assertFalse(agentmemory_http_client.should_proxy_to_api())
        finally:
            agentmemory_http_client.active_provider_name = original_active_provider_name  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
