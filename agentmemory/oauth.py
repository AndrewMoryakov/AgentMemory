from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlparse


AUTH_CODE_TTL_SECONDS = 600
ACCESS_TOKEN_TTL_SECONDS = 7 * 24 * 3600

# Defensive upper bound to keep the on-disk registry small in case /register
# is hammered. Old registrations are evicted FIFO once the cap is hit.
MAX_REGISTERED_CLIENTS = 10_000

CLIENT_STORE_FILENAME = "oauth_clients.json"
CLIENT_STORE_VERSION = 1

TOKEN_STORE_FILENAME = "oauth_tokens.json"
TOKEN_STORE_VERSION = 1

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

_LOCK = Lock()
_AUTH_CODES: dict[str, dict[str, Any]] = {}
_ACCESS_TOKENS: dict[str, dict[str, Any]] = {}
_TOKENS_LOADED = False

_STORE_LOCK = Lock()


def _hash_secret(secret: str) -> str:
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _verify_hashed_secret(presented: str, stored_hash: str) -> bool:
    if not stored_hash.startswith("sha256:"):
        return False
    expected = stored_hash.split(":", 1)[1]
    actual = hashlib.sha256(presented.encode("utf-8")).hexdigest()
    return hmac.compare_digest(expected, actual)


def _client_store_path() -> Path:
    # Lazy import to avoid pulling provider/runtime modules during a plain
    # `python -c "import agentmemory.oauth"` (used in tests / smoke checks).
    from agentmemory.runtime.config import RUNTIME_DIR

    override = os.environ.get("AGENTMEMORY_OAUTH_STORE", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(RUNTIME_DIR) / CLIENT_STORE_FILENAME


def _load_store() -> dict[str, Any]:
    path = _client_store_path()
    if not path.exists():
        return {"version": CLIENT_STORE_VERSION, "clients": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": CLIENT_STORE_VERSION, "clients": {}}
    if not isinstance(payload, dict):
        return {"version": CLIENT_STORE_VERSION, "clients": {}}
    payload.setdefault("version", CLIENT_STORE_VERSION)
    if not isinstance(payload.get("clients"), dict):
        payload["clients"] = {}
    return payload


def _save_store(store: dict[str, Any]) -> None:
    from agentmemory.runtime.atomic_io import atomic_write_json

    path = _client_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, store, ensure_ascii=True, encoding="utf-8")
    _restrict_to_owner(path)


def _restrict_to_owner(path: Path) -> None:
    """Tighten a credential file to 0600 explicitly. tempfile already
    creates the temp at 0600 on POSIX and os.replace preserves it, but
    relying on that is a footgun — make the intent explicit so a future
    swap of atomic_write_json cannot silently widen access. Best-effort:
    Windows ignores most bits."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def static_client_record() -> dict[str, Any] | None:
    client_id = os.environ.get("AGENTMEMORY_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("AGENTMEMORY_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    return {
        "client_id": client_id,
        "client_secret_hash": _hash_secret(client_secret),
        "redirect_uris": [],  # empty = allow any HTTPS / loopback (legacy behavior)
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
        "client_name": "AgentMemory static client",
        "scope": "mcp",
        "registration_origin": "static",
    }


def oauth_enabled() -> bool:
    """Static OAuth credentials are configured.

    This is used by the resource handler to decide whether bearer auth
    is required at all. Enabling DCR by itself does NOT auto-gate the
    API — that would break installs that previously ran anonymously and
    rely on AGENTMEMORY_API_TOKEN being unset.
    """
    return static_client_record() is not None


def oauth_flow_available() -> bool:
    """The OAuth authorize/token flow is reachable in some form.

    Either a static client is configured, or DCR is on so a dynamic
    client can register. Used by the authorize/token handlers to decide
    between serving the flow vs. returning 501.
    """
    if static_client_record() is not None:
        return True
    return dcr_enabled()


def dcr_enabled() -> bool:
    raw = os.environ.get("AGENTMEMORY_OAUTH_DISABLE_DCR", "").strip().lower()
    if raw in {"1", "true", "yes"}:
        return False
    return True


def lookup_client(client_id: str) -> dict[str, Any] | None:
    if not client_id:
        return None
    static = static_client_record()
    if static is not None and static["client_id"] == client_id:
        return static
    with _STORE_LOCK:
        store = _load_store()
        record = store["clients"].get(client_id)
    if record is None:
        return None
    return dict(record)


def verify_client_secret(client_id: str, presented: str | None) -> bool:
    if not client_id or not presented:
        return False
    record = lookup_client(client_id)
    if record is None:
        return False
    return _verify_hashed_secret(presented, record["client_secret_hash"])


def scheme_host_safe(redirect_uri: str) -> bool:
    """Reject scheme-spoofing tricks (http://127.0.0.1.evil.com,
    http://127.0.0.1@evil.com, etc.) by parsing the URI and matching
    the hostname exactly. https permits any host; http only loopback.
    Userinfo is rejected outright."""
    if not redirect_uri:
        return False
    try:
        parsed = urlparse(redirect_uri)
    except ValueError:
        return False
    if parsed.username is not None or parsed.password is not None or "@" in (parsed.netloc or ""):
        return False
    scheme = (parsed.scheme or "").lower()
    hostname = (parsed.hostname or "").lower()
    if scheme == "https":
        return bool(hostname)
    if scheme == "http":
        return hostname in _LOOPBACK_HOSTS
    return False


def redirect_uri_allowed(record: dict[str, Any], redirect_uri: str) -> bool:
    if not scheme_host_safe(redirect_uri):
        return False
    registered = record.get("redirect_uris") or []
    # Static env-configured clients store no allowlist — any safe scheme
    # passes, matching pre-DCR behavior.
    if not registered:
        return True
    return redirect_uri in registered


def _now() -> float:
    return time.time()


def _token_store_path() -> Path:
    from agentmemory.runtime.config import RUNTIME_DIR

    override = os.environ.get("AGENTMEMORY_OAUTH_TOKEN_STORE", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(RUNTIME_DIR) / TOKEN_STORE_FILENAME


def _load_token_store_from_disk() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    path = _token_store_path()
    if not path.exists():
        return {}, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    if not isinstance(payload, dict):
        return {}, {}
    auth_codes = payload.get("auth_codes") if isinstance(payload.get("auth_codes"), dict) else {}
    access_tokens = payload.get("access_tokens") if isinstance(payload.get("access_tokens"), dict) else {}
    return dict(auth_codes), dict(access_tokens)


def _save_token_store() -> None:
    """Persist current in-memory token state. Caller must hold _LOCK."""
    from agentmemory.runtime.atomic_io import atomic_write_json

    path = _token_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {
            "version": TOKEN_STORE_VERSION,
            "auth_codes": _AUTH_CODES,
            "access_tokens": _ACCESS_TOKENS,
        },
        ensure_ascii=True,
        encoding="utf-8",
    )
    _restrict_to_owner(path)


def _ensure_tokens_loaded() -> None:
    """Populate the in-memory token dicts from disk on first use.
    Caller must hold _LOCK."""
    global _TOKENS_LOADED
    if _TOKENS_LOADED:
        return
    auth_codes, access_tokens = _load_token_store_from_disk()
    _AUTH_CODES.update(auth_codes)
    _ACCESS_TOKENS.update(access_tokens)
    _TOKENS_LOADED = True


def _purge_expired() -> bool:
    """Drop expired entries. Returns True iff anything was removed.
    Caller must hold _LOCK."""
    now = _now()
    removed = False
    for store in (_AUTH_CODES, _ACCESS_TOKENS):
        for key in list(store.keys()):
            if store[key]["expires_at"] <= now:
                store.pop(key, None)
                removed = True
    return removed


def issue_auth_code(
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: str | None = None,
    resource: str | None = None,
) -> str:
    code = secrets.token_urlsafe(32)
    with _LOCK:
        _ensure_tokens_loaded()
        _purge_expired()
        _AUTH_CODES[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": (code_challenge_method or "S256").upper(),
            "scope": scope,
            "resource": resource,
            "expires_at": _now() + AUTH_CODE_TTL_SECONDS,
        }
        _save_token_store()
    return code


def consume_auth_code(
    *,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any] | None:
    with _LOCK:
        _ensure_tokens_loaded()
        _purge_expired()
        entry = _AUTH_CODES.pop(code, None)
        if entry is not None:
            _save_token_store()
    if entry is None:
        return None
    if entry["client_id"] != client_id:
        return None
    if entry["redirect_uri"] != redirect_uri:
        return None
    if not _verify_pkce(entry["code_challenge"], entry["code_challenge_method"], code_verifier):
        return None
    return entry


def _verify_pkce(challenge: str, method: str, verifier: str) -> bool:
    if not verifier:
        return False
    # Only S256 is supported. PLAIN is rejected because the challenge equals
    # the verifier, making intercepted auth codes fully replayable.
    if method == "S256":
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return hmac.compare_digest(challenge, expected)
    return False


def issue_access_token(*, client_id: str, scope: str | None = None) -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    with _LOCK:
        _ensure_tokens_loaded()
        _ACCESS_TOKENS[token] = {
            "client_id": client_id,
            "scope": scope,
            "expires_at": _now() + ACCESS_TOKEN_TTL_SECONDS,
        }
        _save_token_store()
    return token, ACCESS_TOKEN_TTL_SECONDS


def validate_access_token(token: str) -> bool:
    if not token:
        return False
    with _LOCK:
        _ensure_tokens_loaded()
        # Only persist if the purge actually removed something — keeps the
        # common (token still valid, nothing expired) path a pure read.
        if _purge_expired():
            _save_token_store()
        return token in _ACCESS_TOKENS


class RegistrationError(Exception):
    def __init__(self, error: str, description: str | None = None) -> None:
        super().__init__(description or error)
        self.error = error
        self.description = description


def _validate_redirect_uri(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise RegistrationError("invalid_redirect_uri", "redirect_uris entries must be non-empty strings")
    if len(value) > 1024:
        raise RegistrationError("invalid_redirect_uri", "redirect_uri exceeds 1024 characters")
    if not scheme_host_safe(value):
        raise RegistrationError(
            "invalid_redirect_uri",
            "redirect_uris must use https:// or loopback (http://127.0.0.1, http://localhost, http://[::1]) "
            "and must not include userinfo",
        )
    return value


def register_client(payload: dict[str, Any]) -> dict[str, Any]:
    """Register a new OAuth client per RFC 7591 and return the client info
    response (including client_secret, which is only ever shown once)."""
    if not isinstance(payload, dict):
        raise RegistrationError("invalid_client_metadata", "Request body must be a JSON object")

    raw_redirects = payload.get("redirect_uris")
    if not isinstance(raw_redirects, list) or not raw_redirects:
        raise RegistrationError("invalid_redirect_uri", "redirect_uris is required and must be a non-empty array")
    if len(raw_redirects) > 16:
        raise RegistrationError("invalid_redirect_uri", "Too many redirect_uris (max 16)")
    validated = [_validate_redirect_uri(item) for item in raw_redirects]
    redirect_uris = list(dict.fromkeys(validated))

    grant_types = payload.get("grant_types") or ["authorization_code"]
    if not isinstance(grant_types, list) or any(not isinstance(g, str) for g in grant_types):
        raise RegistrationError("invalid_client_metadata", "grant_types must be a list of strings")
    if any(g != "authorization_code" for g in grant_types):
        raise RegistrationError(
            "invalid_client_metadata",
            "Only the 'authorization_code' grant_type is supported",
        )

    response_types = payload.get("response_types") or ["code"]
    if not isinstance(response_types, list) or any(not isinstance(r, str) for r in response_types):
        raise RegistrationError("invalid_client_metadata", "response_types must be a list of strings")
    if any(r != "code" for r in response_types):
        raise RegistrationError("invalid_client_metadata", "Only the 'code' response_type is supported")

    token_endpoint_auth_method = payload.get("token_endpoint_auth_method") or "client_secret_post"
    if token_endpoint_auth_method not in {"client_secret_post", "client_secret_basic"}:
        raise RegistrationError(
            "invalid_client_metadata",
            "token_endpoint_auth_method must be client_secret_post or client_secret_basic",
        )

    scope = payload.get("scope")
    if scope is not None and not isinstance(scope, str):
        raise RegistrationError("invalid_client_metadata", "scope must be a string")

    client_name = payload.get("client_name") or "Unnamed MCP client"
    if not isinstance(client_name, str):
        raise RegistrationError("invalid_client_metadata", "client_name must be a string")
    client_name = client_name[:200]

    client_id = secrets.token_urlsafe(24)
    client_secret = secrets.token_urlsafe(32)
    issued_at = int(_now())

    record = {
        "client_id": client_id,
        "client_secret_hash": _hash_secret(client_secret),
        "client_id_issued_at": issued_at,
        "client_secret_expires_at": 0,  # never expires
        "redirect_uris": redirect_uris,
        "grant_types": list(grant_types),
        "response_types": list(response_types),
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "client_name": client_name,
        "scope": scope or "mcp",
        "registration_origin": "dcr",
    }

    with _STORE_LOCK:
        store = _load_store()
        clients = store["clients"]
        if len(clients) >= MAX_REGISTERED_CLIENTS:
            oldest_id = min(
                clients,
                key=lambda cid: clients[cid].get("client_id_issued_at", 0),
            )
            clients.pop(oldest_id, None)
        clients[client_id] = record
        _save_store(store)

    response = {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_id_issued_at": issued_at,
        "client_secret_expires_at": 0,
        "redirect_uris": redirect_uris,
        "grant_types": list(grant_types),
        "response_types": list(response_types),
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "client_name": client_name,
        "scope": scope or "mcp",
    }
    return response


def reset_client_registry_for_tests() -> None:
    """Test-only helper; not part of the public OAuth surface."""
    global _TOKENS_LOADED
    with _STORE_LOCK:
        for path in (_client_store_path(), _token_store_path()):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    with _LOCK:
        _AUTH_CODES.clear()
        _ACCESS_TOKENS.clear()
        _TOKENS_LOADED = False


def _reload_token_store_for_tests() -> None:
    """Simulate a process restart: drop in-memory tokens, force reload
    from disk on next access."""
    global _TOKENS_LOADED
    with _LOCK:
        _AUTH_CODES.clear()
        _ACCESS_TOKENS.clear()
        _TOKENS_LOADED = False
