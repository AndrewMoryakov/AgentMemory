import io
import json
import os
import unittest
from unittest import mock

import agentmemory.api as agentmemory_api


class AgentMemoryApiTests(unittest.TestCase):
    AUTH_ENV_KEYS = (
        "AGENTMEMORY_API_TOKEN",
        "AGENTMEMORY_OAUTH_CLIENT_ID",
        "AGENTMEMORY_OAUTH_CLIENT_SECRET",
    )

    def setUp(self) -> None:
        self._original_auth_env = {key: os.environ.get(key) for key in self.AUTH_ENV_KEYS}
        for key in self.AUTH_ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._original_auth_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _make_handler(self, *, path: str, method: str = "GET", body: bytes = b"{}", headers: dict[str, str] | None = None):
        handler = agentmemory_api.Handler.__new__(agentmemory_api.Handler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(body)), **(headers or {})}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        return handler

    def test_get_health_uses_shared_operation_registry(self) -> None:
        handler = self._make_handler(path="/health")
        captured: list[tuple[int, object]] = []
        original_spec = agentmemory_api.OPERATIONS["health"]
        try:
            agentmemory_api.OPERATIONS["health"] = agentmemory_api.OPERATIONS["health"].__class__(
                name="health",
                mcp_name="memory_health",
                title="Memory Health",
                description="Return runtime information for the shared memory service.",
                input_schema=original_spec.input_schema,
                execute=lambda source: {"ok": True, "via": "registry"},
            )
            handler._send = lambda status, payload: captured.append((status, payload))  # type: ignore[assignment]
            handler.do_GET()
        finally:
            agentmemory_api.OPERATIONS["health"] = original_spec

        self.assertEqual(captured, [(200, {"ok": True, "via": "registry"})])

    def test_get_health_returns_public_liveness_without_auth(self) -> None:
        os.environ["AGENTMEMORY_API_TOKEN"] = "test-token"
        handler = self._make_handler(path="/health")
        captured: list[tuple[int, object]] = []
        original_spec = agentmemory_api.OPERATIONS["health"]
        try:
            agentmemory_api.OPERATIONS["health"] = agentmemory_api.OPERATIONS["health"].__class__(
                name="health",
                mcp_name="memory_health",
                title="Memory Health",
                description="Return runtime information for the shared memory service.",
                input_schema=original_spec.input_schema,
                execute=lambda source: {"ok": True, "via": "registry"},
            )
            handler._send = lambda status, payload: captured.append((status, payload))  # type: ignore[assignment]
            handler.do_GET()
        finally:
            agentmemory_api.OPERATIONS["health"] = original_spec

        self.assertEqual(captured, [(200, {"ok": True})])

    def test_get_health_uses_shared_operation_registry_when_authorized(self) -> None:
        os.environ["AGENTMEMORY_API_TOKEN"] = "test-token"
        handler = self._make_handler(path="/health", headers={"Authorization": "Bearer test-token"})
        captured: list[tuple[int, object]] = []
        original_spec = agentmemory_api.OPERATIONS["health"]
        try:
            agentmemory_api.OPERATIONS["health"] = agentmemory_api.OPERATIONS["health"].__class__(
                name="health",
                mcp_name="memory_health",
                title="Memory Health",
                description="Return runtime information for the shared memory service.",
                input_schema=original_spec.input_schema,
                execute=lambda source: {"ok": True, "via": "registry"},
            )
            handler._send = lambda status, payload: captured.append((status, payload))  # type: ignore[assignment]
            handler.do_GET()
        finally:
            agentmemory_api.OPERATIONS["health"] = original_spec

        self.assertEqual(captured, [(200, {"ok": True, "via": "registry"})])

    def test_get_admin_scopes_uses_shared_operation_registry(self) -> None:
        handler = self._make_handler(path="/admin/scopes?limit=25&kind=user&query=def")
        captured: list[tuple[int, object]] = []
        original_spec = agentmemory_api.OPERATIONS["list_scopes"]
        try:
            agentmemory_api.OPERATIONS["list_scopes"] = agentmemory_api.OPERATIONS["list_scopes"].__class__(
                name="list_scopes",
                mcp_name="memory_list_scopes",
                title="List Scopes",
                description="List known user, agent, and run scopes for the active provider.",
                input_schema=original_spec.input_schema,
                execute=lambda source: {"via": "registry", **source},
            )
            handler._send = lambda status, payload: captured.append((status, payload))  # type: ignore[assignment]
            handler.do_GET()
        finally:
            agentmemory_api.OPERATIONS["list_scopes"] = original_spec

        self.assertEqual(captured, [(200, {"via": "registry", "limit": 25, "kind": "user", "query": "def"})])

    def test_post_search_uses_shared_operation_registry(self) -> None:
        body = json.dumps({"query": "demo"}).encode("utf-8")
        handler = self._make_handler(path="/search", method="POST", body=body)
        captured: list[tuple[int, object]] = []
        original_spec = agentmemory_api.OPERATIONS["search"]
        try:
            agentmemory_api.OPERATIONS["search"] = agentmemory_api.OPERATIONS["search"].__class__(
                name="search",
                mcp_name="memory_search",
                title="Search Memory",
                description="Search shared memory semantically.",
                input_schema=original_spec.input_schema,
                execute=lambda source: {"query": source["query"], "via": "registry"},
            )
            handler._send = lambda status, payload: captured.append((status, payload))  # type: ignore[assignment]
            handler.do_POST()
        finally:
            agentmemory_api.OPERATIONS["search"] = original_spec

        self.assertEqual(captured, [(200, {"query": "demo", "via": "registry"})])

    def test_delete_memory_uses_shared_operation_registry(self) -> None:
        handler = self._make_handler(path="/memories/demo", method="DELETE")
        captured: list[tuple[int, object]] = []
        original_spec = agentmemory_api.OPERATIONS["delete"]
        try:
            agentmemory_api.OPERATIONS["delete"] = agentmemory_api.OPERATIONS["delete"].__class__(
                name="delete",
                mcp_name="memory_delete",
                title="Delete Memory",
                description="Delete a memory by id.",
                input_schema=original_spec.input_schema,
                execute=lambda source: {"id": source["memory_id"], "deleted": True, "via": "registry"},
            )
            handler._send = lambda status, payload: captured.append((status, payload))  # type: ignore[assignment]
            handler.do_DELETE()
        finally:
            agentmemory_api.OPERATIONS["delete"] = original_spec

        self.assertEqual(captured, [(200, {"id": "demo", "deleted": True, "via": "registry"})])

    def test_post_search_rejects_oversized_request_body(self) -> None:
        handler = self._make_handler(path="/search", method="POST", body=b"{}")
        captured: list[tuple[int, object]] = []
        handler._require_auth = lambda: True  # type: ignore[assignment]
        handler._send = lambda status, payload: captured.append((status, payload))  # type: ignore[assignment]
        handler._read_json = mock.Mock(side_effect=agentmemory_api.RequestBodyTooLarge("too large"))

        handler.do_POST()

        self.assertEqual(captured, [(413, {"error_type": "RequestBodyTooLarge", "message": "too large", "error": "too large"})])

    def test_mcp_rejects_oversized_request_body_with_jsonrpc_error(self) -> None:
        handler = self._make_handler(path="/mcp", method="POST", body=b"{}")
        captured: list[tuple[int, object]] = []
        handler._send = lambda status, payload: captured.append((status, payload))  # type: ignore[assignment]
        handler._read_json = mock.Mock(side_effect=agentmemory_api.RequestBodyTooLarge("too large"))

        handler._handle_mcp_post()

        self.assertEqual(captured, [(413, {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "too large"}})])

    def test_read_json_rejects_content_length_above_limit(self) -> None:
        handler = self._make_handler(path="/search", method="POST", body=b"{}")
        handler.headers["Content-Length"] = "9"
        handler.rfile = io.BytesIO(b"123456789")

        with mock.patch.dict(os.environ, {"AGENTMEMORY_MAX_BODY_BYTES": "8"}, clear=False):
            with self.assertRaises(agentmemory_api.RequestBodyTooLarge):
                handler._read_json()

    def test_read_json_rejects_missing_content_length_when_stream_exceeds_limit(self) -> None:
        handler = self._make_handler(path="/search", method="POST", body=b"")
        handler.headers.pop("Content-Length", None)
        handler.rfile = io.BytesIO(b"123456789")

        with mock.patch.dict(os.environ, {"AGENTMEMORY_MAX_BODY_BYTES": "8"}, clear=False):
            with self.assertRaises(agentmemory_api.RequestBodyTooLarge):
                handler._read_json()


if __name__ == "__main__":
    unittest.main()
