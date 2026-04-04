import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from agentmemory_runtime import (
    API_HOST,
    API_PORT,
    ConfigurationError,
    health,
    memory_add,
    memory_delete,
    memory_get,
    memory_list,
    memory_search,
    memory_update,
)


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentMemory/1.0"

    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8")) if raw else {}

    def log_message(self, format, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                self._send(200, health())
                return
            if parsed.path == "/memories":
                result = memory_list(
                    user_id=params.get("user_id", [None])[0],
                    agent_id=params.get("agent_id", [None])[0],
                    run_id=params.get("run_id", [None])[0],
                    limit=int(params.get("limit", [100])[0]),
                )
                self._send(200, result)
                return
            if parsed.path.startswith("/memories/"):
                memory_id = parsed.path.rsplit("/", 1)[-1]
                self._send(200, memory_get(memory_id))
                return
            self._send(404, {"error": "Not found"})
        except ConfigurationError as exc:
            self._send(503, {"error": str(exc)})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_POST(self):
        try:
            if self.path == "/add":
                payload = self._read_json()
                result = memory_add(
                    messages=payload["messages"],
                    user_id=payload.get("user_id"),
                    agent_id=payload.get("agent_id"),
                    run_id=payload.get("run_id"),
                    metadata=payload.get("metadata"),
                    infer=payload.get("infer", True),
                    memory_type=payload.get("memory_type"),
                )
                self._send(200, result)
                return
            if self.path == "/search":
                payload = self._read_json()
                result = memory_search(
                    query=payload["query"],
                    user_id=payload.get("user_id"),
                    agent_id=payload.get("agent_id"),
                    run_id=payload.get("run_id"),
                    limit=payload.get("limit", 10),
                    filters=payload.get("filters"),
                    threshold=payload.get("threshold"),
                    rerank=payload.get("rerank", True),
                )
                self._send(200, result)
                return
            if self.path == "/update":
                payload = self._read_json()
                result = memory_update(memory_id=payload["memory_id"], data=payload["data"], metadata=payload.get("metadata"))
                self._send(200, result)
                return
            self._send(404, {"error": "Not found"})
        except ConfigurationError as exc:
            self._send(503, {"error": str(exc)})
        except KeyError as exc:
            self._send(400, {"error": f"Missing field: {exc.args[0]}"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_DELETE(self):
        try:
            if self.path.startswith("/memories/"):
                memory_id = self.path.rsplit("/", 1)[-1]
                self._send(200, memory_delete(memory_id=memory_id))
                return
            self._send(404, {"error": "Not found"})
        except ConfigurationError as exc:
            self._send(503, {"error": str(exc)})
        except Exception as exc:
            self._send(500, {"error": str(exc)})


def main():
    os.environ["AGENTMEMORY_OWNER_PROCESS"] = "1"
    server = ThreadingHTTPServer((API_HOST, API_PORT), Handler)
    print(f"AgentMemory API listening on http://{API_HOST}:{API_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
