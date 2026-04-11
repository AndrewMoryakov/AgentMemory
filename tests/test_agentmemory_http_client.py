import os
import unittest

import agentmemory.runtime.http_client as agentmemory_http_client
from agentmemory.providers.base import (
    MemoryNotFoundError,
    ProviderCapabilityError,
    ProviderScopeRequiredError,
    ProviderUnavailableError,
    ProviderValidationError,
)


class AgentMemoryHttpClientTests(unittest.TestCase):
    def test_should_proxy_to_api_for_owner_process_proxy_when_not_owner(self) -> None:
        original_runtime_policy = agentmemory_http_client.active_provider_runtime_policy
        original_owner = os.environ.get(agentmemory_http_client.OWNER_ENV)
        try:
            agentmemory_http_client.active_provider_runtime_policy = lambda: {"transport_mode": "owner_process_proxy"}  # type: ignore[assignment]
            os.environ.pop(agentmemory_http_client.OWNER_ENV, None)
            self.assertTrue(agentmemory_http_client.should_proxy_to_api())
        finally:
            agentmemory_http_client.active_provider_runtime_policy = original_runtime_policy  # type: ignore[assignment]
            if original_owner is None:
                os.environ.pop(agentmemory_http_client.OWNER_ENV, None)
            else:
                os.environ[agentmemory_http_client.OWNER_ENV] = original_owner

    def test_should_not_proxy_when_owner_process(self) -> None:
        original_runtime_policy = agentmemory_http_client.active_provider_runtime_policy
        original_owner = os.environ.get(agentmemory_http_client.OWNER_ENV)
        try:
            agentmemory_http_client.active_provider_runtime_policy = lambda: {"transport_mode": "owner_process_proxy"}  # type: ignore[assignment]
            os.environ[agentmemory_http_client.OWNER_ENV] = "1"
            self.assertFalse(agentmemory_http_client.should_proxy_to_api())
        finally:
            agentmemory_http_client.active_provider_runtime_policy = original_runtime_policy  # type: ignore[assignment]
            if original_owner is None:
                os.environ.pop(agentmemory_http_client.OWNER_ENV, None)
            else:
                os.environ[agentmemory_http_client.OWNER_ENV] = original_owner

    def test_should_not_proxy_for_direct_transport(self) -> None:
        original_runtime_policy = agentmemory_http_client.active_provider_runtime_policy
        try:
            agentmemory_http_client.active_provider_runtime_policy = lambda: {"transport_mode": "direct"}  # type: ignore[assignment]
            self.assertFalse(agentmemory_http_client.should_proxy_to_api())
        finally:
            agentmemory_http_client.active_provider_runtime_policy = original_runtime_policy  # type: ignore[assignment]

    def test_should_raise_for_remote_only_transport_without_remote_path(self) -> None:
        original_runtime_policy = agentmemory_http_client.active_provider_runtime_policy
        try:
            agentmemory_http_client.active_provider_runtime_policy = lambda: {"transport_mode": "remote_only"}  # type: ignore[assignment]
            with self.assertRaises(ProviderUnavailableError):
                agentmemory_http_client.should_proxy_to_api()
        finally:
            agentmemory_http_client.active_provider_runtime_policy = original_runtime_policy  # type: ignore[assignment]

    def test_proxy_list_encodes_filters_in_query_string(self) -> None:
        original_ensure_api_running = agentmemory_http_client.ensure_api_running
        original_request = agentmemory_http_client._request
        captured: dict[str, object] = {}
        try:
            agentmemory_http_client.ensure_api_running = lambda: None  # type: ignore[assignment]

            def fake_request(method: str, path: str, payload=None):
                captured["method"] = method
                captured["path"] = path
                return []

            agentmemory_http_client._request = fake_request  # type: ignore[assignment]
            agentmemory_http_client.proxy_list(user_id="demo", filters={"topic": "docs"})
        finally:
            agentmemory_http_client.ensure_api_running = original_ensure_api_running  # type: ignore[assignment]
            agentmemory_http_client._request = original_request  # type: ignore[assignment]

        self.assertEqual(captured["method"], "GET")
        self.assertIn("/memories?", str(captured["path"]))
        self.assertIn("filters=", str(captured["path"]))

    def test_proxy_list_scopes_encodes_query_params(self) -> None:
        original_ensure_api_running = agentmemory_http_client.ensure_api_running
        original_request = agentmemory_http_client._request
        captured: dict[str, object] = {}
        try:
            agentmemory_http_client.ensure_api_running = lambda: None  # type: ignore[assignment]

            def fake_request(method: str, path: str, payload=None):
                captured["method"] = method
                captured["path"] = path
                return {"items": []}

            agentmemory_http_client._request = fake_request  # type: ignore[assignment]
            agentmemory_http_client.proxy_list_scopes(limit=25, kind="user", query="def")
        finally:
            agentmemory_http_client.ensure_api_running = original_ensure_api_running  # type: ignore[assignment]
            agentmemory_http_client._request = original_request  # type: ignore[assignment]

        self.assertEqual(captured["method"], "GET")
        self.assertIn("/admin/scopes?", str(captured["path"]))
        self.assertIn("limit=25", str(captured["path"]))
        self.assertIn("kind=user", str(captured["path"]))
        self.assertIn("query=def", str(captured["path"]))

    def test_ensure_api_running_clears_runtime_cache_after_launcher_start(self) -> None:
        original_api_is_healthy = agentmemory_http_client.api_is_healthy
        original_subprocess_run = agentmemory_http_client.subprocess.run
        original_clear_caches = agentmemory_http_client.clear_caches
        original_time_sleep = agentmemory_http_client.time.sleep
        calls: list[str] = []
        health_checks = iter([False, True])
        try:
            agentmemory_http_client.api_is_healthy = lambda: next(health_checks)  # type: ignore[assignment]
            agentmemory_http_client.subprocess.run = lambda *args, **kwargs: None  # type: ignore[assignment]
            agentmemory_http_client.clear_caches = lambda: calls.append("cleared")  # type: ignore[assignment]
            agentmemory_http_client.time.sleep = lambda *_args, **_kwargs: None  # type: ignore[assignment]

            agentmemory_http_client.ensure_api_running()
        finally:
            agentmemory_http_client.api_is_healthy = original_api_is_healthy  # type: ignore[assignment]
            agentmemory_http_client.subprocess.run = original_subprocess_run  # type: ignore[assignment]
            agentmemory_http_client.clear_caches = original_clear_caches  # type: ignore[assignment]
            agentmemory_http_client.time.sleep = original_time_sleep  # type: ignore[assignment]

        self.assertEqual(calls, ["cleared"])

    def test_http_error_type_maps_to_typed_error(self) -> None:
        original_urlopen = agentmemory_http_client.urlopen
        try:
            class FakeHttpError(agentmemory_http_client.HTTPError):
                def __init__(self):
                    super().__init__(
                        url="http://127.0.0.1:8765/memories/missing",
                        code=404,
                        msg="Not Found",
                        hdrs=None,
                        fp=None,
                    )

                def read(self):
                    return b'{"error":"missing","error_type":"MemoryNotFoundError"}'

            def fake_urlopen(*args, **kwargs):
                raise FakeHttpError()

            agentmemory_http_client.urlopen = fake_urlopen  # type: ignore[assignment]

            with self.assertRaises(MemoryNotFoundError):
                agentmemory_http_client._request("GET", "/memories/missing")
        finally:
            agentmemory_http_client.urlopen = original_urlopen  # type: ignore[assignment]

    def test_unknown_client_error_defaults_to_validation_for_400(self) -> None:
        original_urlopen = agentmemory_http_client.urlopen
        try:
            class FakeHttpError(agentmemory_http_client.HTTPError):
                def __init__(self):
                    super().__init__(
                        url="http://127.0.0.1:8765/memories",
                        code=400,
                        msg="Bad Request",
                        hdrs=None,
                        fp=None,
                    )

                def read(self):
                    return b'{"error":"bad request"}'

            def fake_urlopen(*args, **kwargs):
                raise FakeHttpError()

            agentmemory_http_client.urlopen = fake_urlopen  # type: ignore[assignment]

            with self.assertRaises(ProviderValidationError):
                agentmemory_http_client._request("GET", "/memories")
        finally:
            agentmemory_http_client.urlopen = original_urlopen  # type: ignore[assignment]

    def test_http_error_type_maps_scope_required_to_typed_error(self) -> None:
        original_urlopen = agentmemory_http_client.urlopen
        try:
            class FakeHttpError(agentmemory_http_client.HTTPError):
                def __init__(self):
                    super().__init__(
                        url="http://127.0.0.1:8765/search",
                        code=400,
                        msg="Bad Request",
                        hdrs=None,
                        fp=None,
                    )

                def read(self):
                    return b'{"error":"scope required","error_type":"ProviderScopeRequiredError"}'

            def fake_urlopen(*args, **kwargs):
                raise FakeHttpError()

            agentmemory_http_client.urlopen = fake_urlopen  # type: ignore[assignment]

            with self.assertRaises(ProviderScopeRequiredError):
                agentmemory_http_client._request("POST", "/search", {"query": "demo"})
        finally:
            agentmemory_http_client.urlopen = original_urlopen  # type: ignore[assignment]

    def test_http_error_type_maps_capability_error(self) -> None:
        original_urlopen = agentmemory_http_client.urlopen
        try:
            class FakeHttpError(agentmemory_http_client.HTTPError):
                def __init__(self):
                    super().__init__(
                        url="http://127.0.0.1:8765/search",
                        code=400,
                        msg="Bad Request",
                        hdrs=None,
                        fp=None,
                    )

                def read(self):
                    return b'{"error":"unsupported rerank","error_type":"ProviderCapabilityError"}'

            def fake_urlopen(*args, **kwargs):
                raise FakeHttpError()

            agentmemory_http_client.urlopen = fake_urlopen  # type: ignore[assignment]

            with self.assertRaises(ProviderCapabilityError):
                agentmemory_http_client._request("POST", "/search", {"query": "demo"})
        finally:
            agentmemory_http_client.urlopen = original_urlopen  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
