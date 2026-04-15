import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from agentmemory.runtime.admin import (
    admin_stats,
    delete_admin_memory,
    get_admin_memory,
    list_admin_memories,
    pin_admin_memory,
    update_admin_memory,
)
from agentmemory.runtime.operation_adapters import http_operation_source
from agentmemory.runtime.operations import OPERATIONS
from agentmemory.runtime.config import BASE_DIR, current_api_host, current_api_port
from agentmemory.runtime.transport import (
    provider_error_payload,
    provider_error_status,
)
from agentmemory.providers.base import (
    MemoryNotFoundError,
    ProviderError,
    ProviderValidationError,
)

WEB_DIR = BASE_DIR / "web"


def _extract_memory_id(path: str) -> str:
    memory_id = path.rsplit("/", 1)[-1]
    if not memory_id or memory_id in {"memories", "admin"}:
        raise ProviderValidationError("Missing or empty memory_id in URL path.")
    return memory_id


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentMemory/1.0"

    @staticmethod
    def _client_disconnected(exc: Exception) -> bool:
        return isinstance(exc, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.error))

    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=True, default=str).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            if not self._client_disconnected(exc):
                raise

    def _send_bytes(self, status, body: bytes, content_type: str) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            if not self._client_disconnected(exc):
                raise

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _send_error_payload(self, status: int, exc: Exception) -> None:
        if isinstance(exc, ProviderError):
            self._send(status, provider_error_payload(exc) | {"error": str(exc)})
            return
        self._send(status, {"error": str(exc), "error_type": exc.__class__.__name__})

    def _serve_web_file(self, relative_path: str, content_type: str) -> bool:
        path = (WEB_DIR / relative_path).resolve()
        try:
            path.relative_to(WEB_DIR.resolve())
        except ValueError:
            self._send(404, {"error": "Not found"})
            return True
        if not path.exists():
            self._send(404, {"error": "Not found"})
            return True
        self._send_bytes(200, path.read_bytes(), content_type)
        return True

    def log_message(self, format, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            if parsed.path in {"/", "/ui", "/ui/"}:
                self._serve_web_file("index.html", "text/html; charset=utf-8")
                return
            if parsed.path == "/ui/app.js":
                self._serve_web_file("app.js", "application/javascript; charset=utf-8")
                return
            if parsed.path == "/ui/styles.css":
                self._serve_web_file("styles.css", "text/css; charset=utf-8")
                return
            if parsed.path == "/health":
                self._send(200, OPERATIONS["health"].execute(http_operation_source("health")))
                return
            if parsed.path == "/admin/stats":
                self._send(200, admin_stats(limit=int(params.get("limit", [500])[0])))
                return
            if parsed.path == "/admin/scopes":
                self._send(200, OPERATIONS["list_scopes"].execute(http_operation_source("list_scopes", query_params=params)))
                return
            if parsed.path == "/admin/clients":
                self._send(200, admin_stats(limit=50).get("clients", {}))
                return
            if parsed.path == "/admin/memories":
                try:
                    result = list_admin_memories(
                        query=params.get("query", [None])[0],
                        user_id=params.get("user_id", [None])[0],
                        agent_id=params.get("agent_id", [None])[0],
                        run_id=params.get("run_id", [None])[0],
                        limit=int(params.get("limit", [100])[0]),
                        pinned={"true": True, "false": False}.get((params.get("pinned", [None])[0] or "").lower()),
                        archived={"true": True, "false": False}.get((params.get("archived", [None])[0] or "").lower()),
                        include_archived=(params.get("include_archived", ["false"])[0].lower() == "true"),
                    )
                except ProviderError as exc:
                    result = []
                    self._send(200, {"items": result, "count": len(result), "warning": str(exc)})
                    return
                self._send(200, {"items": result, "count": len(result)})
                return
            if parsed.path.startswith("/admin/memories/"):
                memory_id = _extract_memory_id(parsed.path)
                self._send(200, get_admin_memory(memory_id))
                return
            if parsed.path == "/memories":
                result = OPERATIONS["list"].execute(http_operation_source("list", query_params=params))
                self._send(200, result)
                return
            if parsed.path.startswith("/memories/"):
                memory_id = _extract_memory_id(parsed.path)
                self._send(200, OPERATIONS["get"].execute(http_operation_source("get", path_params={"memory_id": memory_id})))
                return
            self._send(404, {"error": "Not found"})
        except ProviderError as exc:
            self._send_error_payload(provider_error_status(exc), exc)
        except json.JSONDecodeError as exc:
            self._send_error_payload(400, ProviderValidationError(str(exc)))
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_POST(self):
        try:
            if self.path.startswith("/admin/memories/") and self.path.endswith("/pin"):
                memory_id = self.path.removeprefix("/admin/memories/").removesuffix("/pin").rstrip("/")
                payload = self._read_json()
                self._send(200, pin_admin_memory(memory_id, pinned=payload.get("pinned", True)))
                return
            if self.path == "/add":
                payload = self._read_json()
                result = OPERATIONS["add"].execute(http_operation_source("add", payload=payload))
                self._send(200, result)
                return
            if self.path == "/search":
                payload = self._read_json()
                result = OPERATIONS["search"].execute(http_operation_source("search", payload=payload))
                self._send(200, result)
                return
            if self.path == "/update":
                payload = self._read_json()
                result = OPERATIONS["update"].execute(http_operation_source("update", payload=payload))
                self._send(200, result)
                return
            self._send(404, {"error": "Not found"})
        except ProviderError as exc:
            self._send_error_payload(provider_error_status(exc), exc)
        except KeyError as exc:
            self._send_error_payload(400, ProviderValidationError(f"Missing field: {exc.args[0]}"))
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_PATCH(self):
        try:
            if self.path.startswith("/admin/memories/"):
                memory_id = _extract_memory_id(self.path)
                payload = self._read_json()
                result = update_admin_memory(
                    memory_id,
                    memory=payload.get("memory"),
                    metadata=payload.get("metadata"),
                    pinned=payload.get("pinned"),
                    archived=payload.get("archived"),
                )
                self._send(200, result)
                return
            self._send(404, {"error": "Not found"})
        except ProviderError as exc:
            self._send_error_payload(provider_error_status(exc), exc)
        except KeyError as exc:
            self._send_error_payload(404, MemoryNotFoundError(f"Missing memory: {exc.args[0]}"))
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_DELETE(self):
        try:
            if self.path.startswith("/admin/memories/"):
                memory_id = _extract_memory_id(self.path)
                self._send(200, delete_admin_memory(memory_id))
                return
            if self.path.startswith("/memories/"):
                memory_id = _extract_memory_id(self.path)
                self._send(200, OPERATIONS["delete"].execute(http_operation_source("delete", path_params={"memory_id": memory_id})))
                return
            self._send(404, {"error": "Not found"})
        except ProviderError as exc:
            self._send_error_payload(provider_error_status(exc), exc)
        except Exception as exc:
            self._send(500, {"error": str(exc)})


def main():
    os.environ["AGENTMEMORY_OWNER_PROCESS"] = "1"
    api_host = current_api_host()
    api_port = current_api_port()
    server = ThreadingHTTPServer((api_host, api_port), Handler)
    print(f"AgentMemory API listening on http://{api_host}:{api_port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
