import io
import json
import unittest

import agentmemory.api as agentmemory_api
from agentmemory.api import _extract_memory_id, CORS_HEADERS, MAX_REQUEST_BODY_BYTES
from agentmemory.providers.base import ProviderValidationError


class ApiSecurityTests(unittest.TestCase):
    def _make_handler(self, *, path, method="GET", body=b"{}", client_address=("127.0.0.1", 54321)):
        handler = agentmemory_api.Handler.__new__(agentmemory_api.Handler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.client_address = client_address
        return handler

    # --- CORS ---

    def test_do_options_returns_204_with_cors_headers(self) -> None:
        handler = self._make_handler(path="/health")
        captured_status = []
        captured_headers = []
        handler.send_response = lambda status: captured_status.append(status)
        handler.send_header = lambda key, value: captured_headers.append((key, value))
        handler.end_headers = lambda: None

        handler.do_OPTIONS()

        self.assertEqual(captured_status, [204])
        header_dict = dict(captured_headers)
        self.assertEqual(header_dict["Access-Control-Allow-Origin"], "*")
        self.assertIn("GET", header_dict["Access-Control-Allow-Methods"])
        self.assertIn("POST", header_dict["Access-Control-Allow-Methods"])
        self.assertIn("DELETE", header_dict["Access-Control-Allow-Methods"])
        self.assertIn("OPTIONS", header_dict["Access-Control-Allow-Methods"])
        self.assertEqual(header_dict["Content-Length"], "0")

    def test_send_includes_cors_headers(self) -> None:
        handler = self._make_handler(path="/health")
        captured_headers = []
        handler.send_response = lambda status: None
        handler.send_header = lambda key, value: captured_headers.append((key, value))
        handler.end_headers = lambda: None

        handler._send(200, {"ok": True})

        header_dict = dict(captured_headers)
        self.assertEqual(header_dict["Access-Control-Allow-Origin"], "*")
        self.assertIn("Content-Type", header_dict)

    def test_send_bytes_includes_cors_headers(self) -> None:
        handler = self._make_handler(path="/ui")
        captured_headers = []
        handler.send_response = lambda status: None
        handler.send_header = lambda key, value: captured_headers.append((key, value))
        handler.end_headers = lambda: None

        handler._send_bytes(200, b"<html></html>", "text/html")

        header_dict = dict(captured_headers)
        self.assertEqual(header_dict["Access-Control-Allow-Origin"], "*")

    # --- Admin localhost guard ---

    def test_admin_stats_rejects_non_localhost(self) -> None:
        handler = self._make_handler(path="/admin/stats", client_address=("192.168.1.100", 54321))
        captured = []
        handler._send = lambda status, payload: captured.append((status, payload))

        handler.do_GET()

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][0], 403)
        self.assertIn("localhost", captured[0][1]["error"])

    def test_admin_memories_rejects_non_localhost(self) -> None:
        handler = self._make_handler(path="/admin/memories", client_address=("10.0.0.5", 12345))
        captured = []
        handler._send = lambda status, payload: captured.append((status, payload))

        handler.do_GET()

        self.assertEqual(captured[0][0], 403)

    def test_admin_scopes_rejects_non_localhost(self) -> None:
        handler = self._make_handler(path="/admin/scopes", client_address=("172.16.0.1", 12345))
        captured = []
        handler._send = lambda status, payload: captured.append((status, payload))

        handler.do_GET()

        self.assertEqual(captured[0][0], 403)

    def test_admin_post_rejects_non_localhost(self) -> None:
        handler = self._make_handler(path="/admin/memories/abc/pin", method="POST", client_address=("8.8.8.8", 12345))
        captured = []
        handler._send = lambda status, payload: captured.append((status, payload))

        handler.do_POST()

        self.assertEqual(captured[0][0], 403)

    def test_admin_patch_rejects_non_localhost(self) -> None:
        handler = self._make_handler(path="/admin/memories/abc", method="PATCH", client_address=("8.8.8.8", 12345))
        captured = []
        handler._send = lambda status, payload: captured.append((status, payload))

        handler.do_PATCH()

        self.assertEqual(captured[0][0], 403)

    def test_admin_delete_rejects_non_localhost(self) -> None:
        handler = self._make_handler(path="/admin/memories/abc", method="DELETE", client_address=("8.8.8.8", 12345))
        captured = []
        handler._send = lambda status, payload: captured.append((status, payload))

        handler.do_DELETE()

        self.assertEqual(captured[0][0], 403)

    def test_admin_allows_localhost_ipv4(self) -> None:
        handler = self._make_handler(path="/admin/stats", client_address=("127.0.0.1", 54321))
        captured = []
        handler._send = lambda status, payload: captured.append((status, payload))
        original_stats = agentmemory_api.__dict__.get("admin_stats")
        try:
            agentmemory_api.admin_stats = lambda limit: {"stats": "ok"}
            handler.do_GET()
        finally:
            if original_stats:
                agentmemory_api.admin_stats = original_stats

        self.assertEqual(captured[0][0], 200)

    def test_admin_allows_localhost_ipv6(self) -> None:
        handler = self._make_handler(path="/admin/stats", client_address=("::1", 54321))
        captured = []
        handler._send = lambda status, payload: captured.append((status, payload))
        original_stats = agentmemory_api.__dict__.get("admin_stats")
        try:
            agentmemory_api.admin_stats = lambda limit: {"stats": "ok"}
            handler.do_GET()
        finally:
            if original_stats:
                agentmemory_api.admin_stats = original_stats

        self.assertEqual(captured[0][0], 200)

    def test_non_admin_routes_allow_any_client(self) -> None:
        handler = self._make_handler(path="/health", client_address=("8.8.8.8", 12345))
        captured = []
        original_spec = agentmemory_api.OPERATIONS["health"]
        try:
            agentmemory_api.OPERATIONS["health"] = original_spec.__class__(
                name="health",
                mcp_name="memory_health",
                title="Memory Health",
                description="Return runtime information.",
                input_schema=original_spec.input_schema,
                execute=lambda source: {"ok": True},
            )
            handler._send = lambda status, payload: captured.append((status, payload))
            handler.do_GET()
        finally:
            agentmemory_api.OPERATIONS["health"] = original_spec

        self.assertEqual(captured[0][0], 200)

    # --- Body size limit ---

    def test_read_json_rejects_oversized_body(self) -> None:
        handler = self._make_handler(path="/add", body=b"{}")
        handler.headers = {"Content-Length": str(MAX_REQUEST_BODY_BYTES + 1)}

        with self.assertRaises(ProviderValidationError) as ctx:
            handler._read_json()

        self.assertIn("too large", str(ctx.exception))

    def test_read_json_accepts_body_within_limit(self) -> None:
        body = json.dumps({"key": "value"}).encode("utf-8")
        handler = self._make_handler(path="/add", body=body)

        result = handler._read_json()

        self.assertEqual(result, {"key": "value"})

    def test_read_json_returns_empty_dict_for_missing_body(self) -> None:
        handler = self._make_handler(path="/add", body=b"")
        handler.headers = {"Content-Length": "0"}

        result = handler._read_json()

        self.assertEqual(result, {})

    # --- memory_id extraction ---

    def test_extract_memory_id_rejects_empty_id(self) -> None:
        with self.assertRaises(ProviderValidationError):
            _extract_memory_id("/memories/")

    def test_extract_memory_id_rejects_bare_path(self) -> None:
        with self.assertRaises(ProviderValidationError):
            _extract_memory_id("/admin/memories")

    def test_extract_memory_id_extracts_valid_id(self) -> None:
        self.assertEqual(_extract_memory_id("/memories/abc-123"), "abc-123")
        self.assertEqual(_extract_memory_id("/admin/memories/xyz"), "xyz")


if __name__ == "__main__":
    unittest.main()
