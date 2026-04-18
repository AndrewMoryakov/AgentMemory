from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from threading import Lock
from typing import Any


AUTH_CODE_TTL_SECONDS = 600
ACCESS_TOKEN_TTL_SECONDS = 7 * 24 * 3600

_LOCK = Lock()
_AUTH_CODES: dict[str, dict[str, Any]] = {}
_ACCESS_TOKENS: dict[str, dict[str, Any]] = {}


def client_credentials() -> tuple[str, str] | None:
    client_id = os.environ.get("AGENTMEMORY_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("AGENTMEMORY_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    return client_id, client_secret


def verify_client_secret(presented: str) -> bool:
    creds = client_credentials()
    if creds is None:
        return False
    return hmac.compare_digest(presented, creds[1])


def oauth_enabled() -> bool:
    return client_credentials() is not None


def _now() -> float:
    return time.time()


def _purge_expired() -> None:
    now = _now()
    for store in (_AUTH_CODES, _ACCESS_TOKENS):
        for key in list(store.keys()):
            if store[key]["expires_at"] <= now:
                store.pop(key, None)


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
    return code


def consume_auth_code(
    *,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any] | None:
    with _LOCK:
        _purge_expired()
        entry = _AUTH_CODES.pop(code, None)
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
    if method == "PLAIN":
        return hmac.compare_digest(challenge, verifier)
    if method == "S256":
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return hmac.compare_digest(challenge, expected)
    return False


def issue_access_token(*, client_id: str, scope: str | None = None) -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    with _LOCK:
        _ACCESS_TOKENS[token] = {
            "client_id": client_id,
            "scope": scope,
            "expires_at": _now() + ACCESS_TOKEN_TTL_SECONDS,
        }
    return token, ACCESS_TOKEN_TTL_SECONDS


def validate_access_token(token: str) -> bool:
    if not token:
        return False
    with _LOCK:
        _purge_expired()
        return token in _ACCESS_TOKENS
