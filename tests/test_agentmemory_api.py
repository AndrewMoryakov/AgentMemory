import io
import json
import unittest

import agentmemory.api as agentmemory_api


class AgentMemoryApiTests(unittest.TestCase):
    def _make_handler(self, *, path: str, method: str = "GET", body: bytes = b"{}"):
        handler = agentmemory_api.Handler.__new__(agentmemory_api.Handler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(body))}
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


if __name__ == "__main__":
    unittest.main()
