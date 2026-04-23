import atexit
import base64
import math
import hmac
import json
import mimetypes
import os
import signal
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from agentmemory import mcp as mcp_server
from agentmemory import oauth as oauth_state
from agentmemory.runtime.admin import (
    admin_stats,
    delete_admin_memory,
    get_admin_memory,
    list_admin_memories,
    pin_admin_memory,
    update_admin_memory,
)
from agentmemory.runtime import lifecycle as lifecycle_module
from agentmemory.runtime import metrics as metrics_registry
from agentmemory.runtime.operation_adapters import http_operation_source
from agentmemory.runtime.operations import OPERATIONS
from agentmemory.runtime.config import (
    API_PID_FILE,
    API_STATE_FILE,
    BASE_DIR,
    current_api_host,
    current_api_port,
    remove_api_state,
    write_api_state,
)
from agentmemory.runtime.transport import (
    provider_error_payload,
    provider_error_status,
)
from agentmemory.providers.base import (
    MemoryNotFoundError,
    ProviderError,
    ProviderValidationError,
)

WEB_DIR = BASE_DIR / "web" / "dist"
SPA_ROUTES = {"/", "/me"}
SPA_ROOT_ASSETS = {"/favicon.ico", "/vite.svg", "/manifest.webmanifest", "/robots.txt"}
DEFAULT_MAX_BODY_BYTES = 16 * 1024 * 1024
DEFAULT_RATE_LIMIT_PER_MINUTE = 60


class RequestBodyTooLarge(ProviderValidationError):
    pass


class RateLimitExceeded(ProviderError):
    pass


def _parse_int_query_param(
    params: dict[str, list[str]],
    name: str,
    *,
    default: int,
    minimum: int | None = None,
) -> int:
    raw = (params.get(name) or [str(default)])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ProviderValidationError(f"Query parameter '{name}' must be an integer.") from exc
    if minimum is not None and value < minimum:
        raise ProviderValidationError(f"Query parameter '{name}' must be at least {minimum}.")
    return value


class _TokenBucketLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def allow(self, key: str, *, capacity: int, period_seconds: float = 60.0) -> tuple[bool, int]:
        if capacity <= 0:
            return True, 0
        now = time.monotonic()
        refill_per_second = capacity / period_seconds
        with self._lock:
            tokens, updated_at = self._buckets.get(key, (float(capacity), now))
            elapsed = max(0.0, now - updated_at)
            tokens = min(float(capacity), tokens + (elapsed * refill_per_second))
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return True, 0
            retry_after = max(1, math.ceil((1.0 - tokens) / refill_per_second))
            self._buckets[key] = (tokens, now)
            return False, retry_after


_RATE_LIMITER = _TokenBucketLimiter()


def _max_body_bytes() -> int:
    raw = os.environ.get("AGENTMEMORY_MAX_BODY_BYTES", "").strip()
    if not raw:
        return DEFAULT_MAX_BODY_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_BODY_BYTES
    return value if value > 0 else DEFAULT_MAX_BODY_BYTES


def _configured_token() -> str | None:
    token = os.environ.get("AGENTMEMORY_API_TOKEN", "").strip()
    return token or None


def _rate_limit_per_minute() -> int:
    raw = os.environ.get("AGENTMEMORY_RATE_LIMIT_PER_MINUTE", "").strip()
    if not raw:
        return DEFAULT_RATE_LIMIT_PER_MINUTE
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_RATE_LIMIT_PER_MINUTE
    return value if value > 0 else DEFAULT_RATE_LIMIT_PER_MINUTE


def _ui_disabled() -> bool:
    return os.environ.get("AGENTMEMORY_DISABLE_UI", "").strip() in {"1", "true", "yes"}


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentMemory/1.0"

    @staticmethod
    def _client_disconnected(exc: Exception) -> bool:
        return isinstance(exc, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.error))

    def _send(self, status, payload, headers: dict[str, str] | None = None):
        body = json.dumps(payload, ensure_ascii=True, default=str).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            if not self._client_disconnected(exc):
                raise

    def _send_bytes(self, status, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            if not self._client_disconnected(exc):
                raise

    def _read_json(self):
        raw = self._read_request_body()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _read_request_body(self) -> bytes:
        max_body_bytes = _max_body_bytes()
        length_header = self.headers.get("Content-Length")
        if length_header is not None:
            try:
                declared_length = int(length_header)
            except ValueError as exc:
                raise ProviderValidationError("Invalid Content-Length header.") from exc
            if declared_length < 0:
                raise ProviderValidationError("Invalid Content-Length header.")
            if declared_length > max_body_bytes:
                raise RequestBodyTooLarge(
                    f"Request body exceeds {max_body_bytes} bytes. Set AGENTMEMORY_MAX_BODY_BYTES to override."
                )
            return self.rfile.read(declared_length) if declared_length else b"{}"

        raw = self.rfile.read(max_body_bytes + 1)
        if len(raw) > max_body_bytes:
            raise RequestBodyTooLarge(
                f"Request body exceeds {max_body_bytes} bytes. Set AGENTMEMORY_MAX_BODY_BYTES to override."
            )
        return raw or b"{}"

    def _send_error_payload(self, status: int, exc: Exception) -> None:
        if isinstance(exc, ProviderError):
            self._send(status, provider_error_payload(exc) | {"error": str(exc)})
            return
        self._send(status, {"error": str(exc), "error_type": exc.__class__.__name__})

    def _public_base_url(self) -> str:
        override = os.environ.get("AGENTMEMORY_PUBLIC_URL", "").strip().rstrip("/")
        if override:
            return override
        scheme = (self.headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip() or "http"
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").split(",")[0].strip()
        prefix = (self.headers.get("X-Forwarded-Prefix") or "").rstrip("/")
        return f"{scheme}://{host}{prefix}"

    def _presented_bearer(self) -> str | None:
        header = self.headers.get("Authorization", "")
        if not header.lower().startswith("bearer "):
            return None
        token = header[7:].strip()
        return token or None

    def _authorized_bearer(self) -> str | None:
        expected = _configured_token()
        oauth_on = oauth_state.oauth_enabled()
        presented = self._presented_bearer()
        if presented is None:
            return None
        if expected is not None and hmac.compare_digest(presented, expected):
            return presented
        if oauth_on and oauth_state.validate_access_token(presented):
            return presented
        return None

    def _is_authorized(self) -> bool:
        expected = _configured_token()
        oauth_on = oauth_state.oauth_enabled()
        if expected is None and not oauth_on:
            return True
        return self._authorized_bearer() is not None

    def _rate_limit_key(self) -> str | None:
        bearer = self._authorized_bearer()
        if bearer is not None:
            return f"bearer:{bearer}"
        return None

    def _require_rate_limit(self, key: str | None) -> bool:
        if key is None:
            return True
        allowed, retry_after = _RATE_LIMITER.allow(key, capacity=_rate_limit_per_minute())
        if allowed:
            return True
        self._send(
            429,
            {
                "error": "Rate limit exceeded",
                "error_type": "RateLimitExceeded",
                "message": "Too many requests. Retry later.",
            },
            headers={"Retry-After": str(retry_after)},
        )
        return False

    def _require_auth(self) -> bool:
        if self._is_authorized():
            return True
        try:
            self.send_response(401)
            if oauth_state.oauth_enabled():
                base = self._public_base_url()
                metadata_url = f"{base}/.well-known/oauth-protected-resource"
                self.send_header(
                    "WWW-Authenticate",
                    f'Bearer realm="agentmemory", resource_metadata="{metadata_url}"',
                )
            else:
                self.send_header("WWW-Authenticate", 'Bearer realm="agentmemory"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = json.dumps({"error": "Unauthorized", "error_type": "AuthRequired"}).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            if not self._client_disconnected(exc):
                raise
        return False

    def _handle_oauth_metadata(self) -> None:
        base = self._public_base_url()
        self._send(200, {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
            "scopes_supported": ["mcp"],
        })

    def _handle_resource_metadata(self) -> None:
        base = self._public_base_url()
        self._send(200, {
            "resource": f"{base}/mcp",
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
            "scopes_supported": ["mcp"],
        })

    def _handle_oauth_authorize(self, params: dict[str, list[str]]) -> None:
        creds = oauth_state.client_credentials()
        if creds is None:
            self._send(501, {"error": "oauth_disabled"})
            return
        expected_client_id, _ = creds

        def _p(name: str, default: str = "") -> str:
            return (params.get(name) or [default])[0]

        given_client_id = _p("client_id")
        redirect_uri = _p("redirect_uri")
        response_type = _p("response_type")
        code_challenge = _p("code_challenge")
        code_challenge_method = _p("code_challenge_method", "S256")
        state = _p("state")
        scope = _p("scope") or None
        resource = _p("resource") or None

        if given_client_id != expected_client_id:
            self._send(400, {"error": "invalid_client"})
            return
        if not (redirect_uri.startswith("https://") or redirect_uri.startswith("http://127.0.0.1") or redirect_uri.startswith("http://localhost")):
            self._send(400, {"error": "invalid_request", "error_description": "redirect_uri must be https or loopback"})
            return
        if response_type != "code":
            self._send(400, {"error": "unsupported_response_type"})
            return
        if not code_challenge:
            self._send(400, {"error": "invalid_request", "error_description": "code_challenge required"})
            return
        if code_challenge_method.upper() not in {"S256", "PLAIN"}:
            self._send(400, {"error": "invalid_request", "error_description": "unsupported code_challenge_method"})
            return

        code = oauth_state.issue_auth_code(
            client_id=expected_client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            resource=resource,
        )

        sep = "&" if "?" in redirect_uri else "?"
        location = f"{redirect_uri}{sep}code={quote(code, safe='')}"
        if state:
            location += f"&state={quote(state, safe='')}"

        try:
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
        except Exception as exc:
            if not self._client_disconnected(exc):
                raise

    def _handle_oauth_token(self) -> None:
        creds = oauth_state.client_credentials()
        if creds is None:
            self._send(501, {"error": "oauth_disabled"})
            return
        expected_client_id, _ = creds

        raw = self._read_request_body().decode("utf-8")
        form = parse_qs(raw, keep_blank_values=True)

        def _f(name: str, default: str = "") -> str:
            return (form.get(name) or [default])[0]

        given_client_id = _f("client_id")
        given_client_secret = _f("client_secret")

        auth_header = self.headers.get("Authorization", "")
        if auth_header.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                basic_id, _, basic_secret = decoded.partition(":")
                if not given_client_id:
                    given_client_id = basic_id
                if not given_client_secret:
                    given_client_secret = basic_secret
            except Exception:
                pass

        client_key = given_client_id or "anonymous"
        if not self._require_rate_limit(f"oauth-client:{client_key}"):
            return

        if given_client_id != expected_client_id or not oauth_state.verify_client_secret(given_client_secret):
            self._send(401, {"error": "invalid_client"})
            return

        grant_type = _f("grant_type")
        if grant_type != "authorization_code":
            self._send(400, {"error": "unsupported_grant_type"})
            return

        entry = oauth_state.consume_auth_code(
            code=_f("code"),
            client_id=expected_client_id,
            redirect_uri=_f("redirect_uri"),
            code_verifier=_f("code_verifier"),
        )
        if entry is None:
            self._send(400, {"error": "invalid_grant"})
            return

        token, ttl = oauth_state.issue_access_token(client_id=expected_client_id, scope=entry.get("scope"))
        payload = {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": ttl,
        }
        if entry.get("scope"):
            payload["scope"] = entry["scope"]
        self._send(200, payload)

    def _serve_web_file(self, relative_path: str, content_type: str | None = None) -> bool:
        path = (WEB_DIR / relative_path).resolve()
        try:
            path.relative_to(WEB_DIR.resolve())
        except ValueError:
            self._send(404, {"error": "Not found"})
            return True
        if not path.exists() or not path.is_file():
            self._send(404, {"error": "Not found"})
            return True
        if content_type is None:
            guessed, _ = mimetypes.guess_type(str(path))
            content_type = guessed or "application/octet-stream"
        self._send_bytes(200, path.read_bytes(), content_type)
        return True

    def _serve_spa_shell(self) -> bool:
        index = WEB_DIR / "index.html"
        if not index.exists():
            self._send(
                503,
                {
                    "error": "UI bundle not built. Run 'npm install && npm run build' in web/.",
                },
            )
            return True
        return self._serve_web_file("index.html", "text/html; charset=utf-8")

    def log_message(self, format, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            if parsed.path in SPA_ROUTES:
                if _ui_disabled():
                    self._send(404, {"error": "UI disabled"})
                    return
                self._serve_spa_shell()
                return
            if parsed.path.startswith("/assets/"):
                if _ui_disabled():
                    self._send(404, {"error": "UI disabled"})
                    return
                self._serve_web_file(parsed.path.lstrip("/"))
                return
            if parsed.path in SPA_ROOT_ASSETS:
                if _ui_disabled():
                    self._send(404, {"error": "UI disabled"})
                    return
                self._serve_web_file(parsed.path.lstrip("/"))
                return
            if parsed.path == "/health":
                if self._is_authorized():
                    self._send(200, OPERATIONS["health"].execute(http_operation_source("health")))
                else:
                    self._send(200, {"ok": True})
                return
            if parsed.path == "/metrics":
                if not self._require_auth():
                    return
                if not self._require_rate_limit(self._rate_limit_key()):
                    return
                body = metrics_registry.prometheus_text().encode("utf-8")
                self._send_bytes(200, body, "text/plain; version=0.0.4; charset=utf-8")
                return
            if parsed.path == "/.well-known/oauth-authorization-server" or parsed.path.startswith("/.well-known/oauth-authorization-server/"):
                self._handle_oauth_metadata()
                return
            if parsed.path == "/.well-known/oauth-protected-resource" or parsed.path.startswith("/.well-known/oauth-protected-resource/"):
                self._handle_resource_metadata()
                return
            if parsed.path == "/oauth/authorize":
                self._handle_oauth_authorize(params)
                return
            if not self._require_auth():
                return
            if not self._require_rate_limit(self._rate_limit_key()):
                return
            if parsed.path == "/admin/stats":
                self._send(200, admin_stats(limit=_parse_int_query_param(params, "limit", default=500, minimum=1)))
                return
            if parsed.path == "/admin/stats/operations":
                self._send(200, metrics_registry.summary())
                return
            if parsed.path == "/admin/scopes":
                self._send(200, OPERATIONS["list_scopes"].execute(http_operation_source("list_scopes", query_params=params)))
                return
            if parsed.path == "/admin/scopes/page":
                self._send(200, OPERATIONS["list_scopes_page"].execute(http_operation_source("list_scopes_page", query_params=params)))
                return
            if parsed.path == "/admin/clients":
                self._send(200, admin_stats(limit=50).get("clients", {}))
                return
            if parsed.path == "/admin/memories":
                limit = _parse_int_query_param(params, "limit", default=100, minimum=1)
                try:
                    result = list_admin_memories(
                        query=params.get("query", [None])[0],
                        user_id=params.get("user_id", [None])[0],
                        agent_id=params.get("agent_id", [None])[0],
                        run_id=params.get("run_id", [None])[0],
                        limit=limit,
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
                memory_id = parsed.path.rsplit("/", 1)[-1]
                self._send(200, get_admin_memory(memory_id))
                return
            if parsed.path == "/memories":
                result = OPERATIONS["list"].execute(http_operation_source("list", query_params=params))
                self._send(200, result)
                return
            if parsed.path == "/memories/page":
                result = OPERATIONS["list_page"].execute(http_operation_source("list_page", query_params=params))
                self._send(200, result)
                return
            if parsed.path.startswith("/memories/"):
                memory_id = parsed.path.rsplit("/", 1)[-1]
                self._send(200, OPERATIONS["get"].execute(http_operation_source("get", path_params={"memory_id": memory_id})))
                return
            self._send(404, {"error": "Not found"})
        except ProviderError as exc:
            if isinstance(exc, RequestBodyTooLarge):
                self._send_error_payload(413, exc)
                return
            self._send_error_payload(provider_error_status(exc), exc)
        except json.JSONDecodeError as exc:
            self._send_error_payload(400, ProviderValidationError(str(exc)))
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_POST(self):
        try:
            if self.path == "/oauth/token":
                self._handle_oauth_token()
                return
            if not self._require_auth():
                return
            if not self._require_rate_limit(self._rate_limit_key()):
                return
            if self.path == "/mcp":
                self._handle_mcp_post()
                return
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
            if self.path == "/search/page":
                payload = self._read_json()
                result = OPERATIONS["search_page"].execute(http_operation_source("search_page", payload=payload))
                self._send(200, result)
                return
            if self.path == "/update":
                payload = self._read_json()
                result = OPERATIONS["update"].execute(http_operation_source("update", payload=payload))
                self._send(200, result)
                return
            self._send(404, {"error": "Not found"})
        except ProviderError as exc:
            if isinstance(exc, RequestBodyTooLarge):
                self._send_error_payload(413, exc)
                return
            self._send_error_payload(provider_error_status(exc), exc)
        except KeyError as exc:
            self._send_error_payload(400, ProviderValidationError(f"Missing field: {exc.args[0]}"))
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def _handle_mcp_post(self) -> None:
        try:
            incoming = self._read_json()
        except RequestBodyTooLarge as exc:
            self._send(413, {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": str(exc)}})
            return
        except json.JSONDecodeError as exc:
            self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}})
            return

        try:
            if isinstance(incoming, list):
                responses = []
                for item in incoming:
                    response = mcp_server.handle_request(item)
                    if response is not None:
                        responses.append(response)
                if not responses:
                    self.send_response(204)
                    self.end_headers()
                    return
                self._send(200, responses)
                return

            response = mcp_server.handle_request(incoming)
            if response is None:
                self.send_response(204)
                self.end_headers()
                return
            self._send(200, response)
        except Exception as exc:
            traceback.print_exc()
            request_id = incoming.get("id") if isinstance(incoming, dict) else None
            self._send(500, {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(exc)}})

    def do_PATCH(self):
        try:
            if not self._require_auth():
                return
            if not self._require_rate_limit(self._rate_limit_key()):
                return
            if self.path.startswith("/admin/memories/"):
                memory_id = self.path.rsplit("/", 1)[-1]
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
            if isinstance(exc, RequestBodyTooLarge):
                self._send_error_payload(413, exc)
                return
            self._send_error_payload(provider_error_status(exc), exc)
        except KeyError as exc:
            self._send_error_payload(404, MemoryNotFoundError(f"Missing memory: {exc.args[0]}"))
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_DELETE(self):
        try:
            if not self._require_auth():
                return
            if not self._require_rate_limit(self._rate_limit_key()):
                return
            if self.path.startswith("/admin/memories/"):
                memory_id = self.path.rsplit("/", 1)[-1]
                self._send(200, delete_admin_memory(memory_id))
                return
            if self.path.startswith("/memories/"):
                memory_id = self.path.rsplit("/", 1)[-1]
                self._send(200, OPERATIONS["delete"].execute(http_operation_source("delete", path_params={"memory_id": memory_id})))
                return
            self._send(404, {"error": "Not found"})
        except ProviderError as exc:
            self._send_error_payload(provider_error_status(exc), exc)
        except Exception as exc:
            self._send(500, {"error": str(exc)})


def _record_supervisor_files(*, host: str, port: int) -> None:
    API_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    API_PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    write_api_state(pid=os.getpid(), host=host, port=port)


def _cleanup_supervisor_files() -> None:
    try:
        API_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        remove_api_state()
    except Exception:
        pass


def _install_signal_handlers() -> None:
    def handler(signum, _frame):
        _cleanup_supervisor_files()
        sys.exit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


def _start_ttl_sweeper() -> None:
    # Lazy import so a misconfigured provider doesn't abort startup — the
    # sweeper is opt-in and should degrade gracefully.
    try:
        from agentmemory.runtime.config import (
            memory_delete as _memory_delete,
            memory_list as _memory_list,
            memory_list_expired_ids as _memory_list_expired_ids,
            memory_list_scopes as _memory_list_scopes,
        )
    except Exception:
        return
    try:
        lifecycle_module.start_sweeper_thread(
            list_scopes=_memory_list_scopes,
            list_memories=_memory_list,
            delete_memory=_memory_delete,
            list_expired_memory_ids=_memory_list_expired_ids,
        )
    except Exception:
        pass


def main():
    os.environ["AGENTMEMORY_OWNER_PROCESS"] = "1"
    api_host = current_api_host()
    api_port = current_api_port()
    server = ThreadingHTTPServer((api_host, api_port), Handler)
    _record_supervisor_files(host=api_host, port=api_port)
    atexit.register(_cleanup_supervisor_files)
    _install_signal_handlers()
    _start_ttl_sweeper()
    print(f"AgentMemory API listening on http://{api_host}:{api_port}")
    try:
        server.serve_forever()
    finally:
        _cleanup_supervisor_files()


if __name__ == "__main__":
    main()
