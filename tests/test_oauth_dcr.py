"""Tests for Dynamic Client Registration (RFC 7591) and the related OAuth
authorize / token flow integration."""

import base64
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

import agentmemory.api as agentmemory_api
import agentmemory.oauth as oauth_state

from tests._handler_factory import make_handler as _make_handler


AUTH_ENV_KEYS = (
    "AGENTMEMORY_API_TOKEN",
    "AGENTMEMORY_OAUTH_CLIENT_ID",
    "AGENTMEMORY_OAUTH_CLIENT_SECRET",
    "AGENTMEMORY_OAUTH_STORE",
    "AGENTMEMORY_OAUTH_TOKEN_STORE",
    "AGENTMEMORY_OAUTH_DISABLE_DCR",
    "AGENTMEMORY_RATE_LIMIT_PER_MINUTE",
    "AGENTMEMORY_REGISTER_RATE_LIMIT_PER_HOUR",
    "AGENTMEMORY_PUBLIC_URL",
)


def _pkce_pair():
    verifier = "abcdef0123456789abcdef0123456789abcdef0123456789"  # 48 chars
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class OAuthDcrTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_env = {key: os.environ.get(key) for key in AUTH_ENV_KEYS}
        for key in AUTH_ENV_KEYS:
            os.environ.pop(key, None)

        self._tmpdir = tempfile.TemporaryDirectory()
        self._store_path = Path(self._tmpdir.name) / "oauth_clients.json"
        self._token_store_path = Path(self._tmpdir.name) / "oauth_tokens.json"
        os.environ["AGENTMEMORY_OAUTH_STORE"] = str(self._store_path)
        os.environ["AGENTMEMORY_OAUTH_TOKEN_STORE"] = str(self._token_store_path)
        os.environ["AGENTMEMORY_PUBLIC_URL"] = "https://example.test"

        agentmemory_api._RATE_LIMITER.reset()
        oauth_state.reset_client_registry_for_tests()

    def tearDown(self) -> None:
        agentmemory_api._RATE_LIMITER.reset()
        oauth_state.reset_client_registry_for_tests()
        self._tmpdir.cleanup()
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # ---------- discovery ----------

    def test_oauth_metadata_advertises_registration_endpoint(self) -> None:
        handler = _make_handler(path="/.well-known/oauth-authorization-server", method="GET")
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload))

        handler._handle_oauth_metadata()

        self.assertEqual(len(captured), 1)
        status, payload = captured[0]
        self.assertEqual(status, 200)
        self.assertEqual(payload["registration_endpoint"], "https://example.test/register")
        self.assertEqual(payload["registration_endpoint_auth_methods_supported"], ["none"])

    def test_oauth_metadata_omits_registration_when_dcr_disabled(self) -> None:
        os.environ["AGENTMEMORY_OAUTH_DISABLE_DCR"] = "1"
        handler = _make_handler(path="/.well-known/oauth-authorization-server", method="GET")
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload))

        handler._handle_oauth_metadata()

        _, payload = captured[0]
        self.assertNotIn("registration_endpoint", payload)

    # ---------- registration ----------

    def test_register_creates_client_and_returns_201(self) -> None:
        body = json.dumps({
            "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
            "client_name": "Claude (web)",
            "scope": "mcp",
        }).encode("utf-8")
        handler = _make_handler(path="/register", body=body)
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload, headers or {}))

        handler.do_POST()

        self.assertEqual(len(captured), 1)
        status, payload, headers = captured[0]
        self.assertEqual(status, 201)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertIn("client_id", payload)
        self.assertIn("client_secret", payload)
        self.assertEqual(payload["redirect_uris"], ["https://claude.ai/api/mcp/auth_callback"])
        self.assertEqual(payload["token_endpoint_auth_method"], "client_secret_post")
        self.assertEqual(payload["client_secret_expires_at"], 0)
        self.assertTrue(self._store_path.exists())
        stored = json.loads(self._store_path.read_text(encoding="utf-8"))
        self.assertIn(payload["client_id"], stored["clients"])
        self.assertNotIn("client_secret", stored["clients"][payload["client_id"]])

    def test_register_rejects_non_https_redirect_uri(self) -> None:
        body = json.dumps({"redirect_uris": ["http://attacker.example/cb"]}).encode("utf-8")
        handler = _make_handler(path="/register", body=body)
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload))

        handler.do_POST()

        self.assertEqual(captured[0][0], 400)
        self.assertEqual(captured[0][1]["error"], "invalid_redirect_uri")

    def test_register_rejects_empty_redirect_uris(self) -> None:
        body = json.dumps({"redirect_uris": []}).encode("utf-8")
        handler = _make_handler(path="/register", body=body)
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload))

        handler.do_POST()

        self.assertEqual(captured[0][0], 400)
        self.assertEqual(captured[0][1]["error"], "invalid_redirect_uri")

    def test_register_rejects_userinfo_spoofing(self) -> None:
        # http://127.0.0.1@evil.example/cb has loopback as USERINFO, not host
        body = json.dumps({"redirect_uris": ["http://127.0.0.1@evil.example/cb"]}).encode("utf-8")
        handler = _make_handler(path="/register", body=body)
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload))

        handler.do_POST()

        self.assertEqual(captured[0][0], 400)
        self.assertEqual(captured[0][1]["error"], "invalid_redirect_uri")

    def test_register_rejects_loopback_prefix_spoofing(self) -> None:
        body = json.dumps({"redirect_uris": ["http://127.0.0.1.evil.example/cb"]}).encode("utf-8")
        handler = _make_handler(path="/register", body=body)
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload))

        handler.do_POST()

        self.assertEqual(captured[0][0], 400)
        self.assertEqual(captured[0][1]["error"], "invalid_redirect_uri")

    def test_register_rejects_unsupported_grant_type(self) -> None:
        body = json.dumps({
            "redirect_uris": ["https://x.example/cb"],
            "grant_types": ["password"],
        }).encode("utf-8")
        handler = _make_handler(path="/register", body=body)
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload))

        handler.do_POST()

        self.assertEqual(captured[0][0], 400)
        self.assertEqual(captured[0][1]["error"], "invalid_client_metadata")

    def test_register_returns_429_when_per_ip_hourly_limit_exceeded(self) -> None:
        os.environ["AGENTMEMORY_REGISTER_RATE_LIMIT_PER_HOUR"] = "2"
        body = json.dumps({"redirect_uris": ["https://x.example/cb"]}).encode("utf-8")

        captured: list = []
        for _ in range(3):
            handler = _make_handler(path="/register", body=body)
            handler._send = lambda status, payload, headers=None: captured.append((status, payload, headers or {}))
            handler.do_POST()

        self.assertEqual(captured[0][0], 201)
        self.assertEqual(captured[1][0], 201)
        self.assertEqual(captured[2][0], 429)
        self.assertEqual(captured[2][1]["error_type"], "RateLimitExceeded")
        self.assertIn("Retry-After", captured[2][2])

    def test_register_disabled_returns_404(self) -> None:
        os.environ["AGENTMEMORY_OAUTH_DISABLE_DCR"] = "1"
        body = json.dumps({"redirect_uris": ["https://x.example/cb"]}).encode("utf-8")
        handler = _make_handler(path="/register", body=body)
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload))

        handler.do_POST()

        self.assertEqual(captured[0][0], 404)

    # ---------- end-to-end: register → authorize → token ----------

    def _register_client(self, redirect_uri: str) -> dict:
        body = json.dumps({"redirect_uris": [redirect_uri]}).encode("utf-8")
        handler = _make_handler(path="/register", body=body)
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload))
        handler.do_POST()
        self.assertEqual(captured[0][0], 201, captured)
        return captured[0][1]

    def test_full_flow_register_authorize_token(self) -> None:
        redirect_uri = "https://claude.ai/api/mcp/auth_callback"
        client = self._register_client(redirect_uri)
        verifier, challenge = _pkce_pair()

        # authorize
        params = {
            "client_id": [client["client_id"]],
            "redirect_uri": [redirect_uri],
            "response_type": ["code"],
            "code_challenge": [challenge],
            "code_challenge_method": ["S256"],
            "state": ["xyz"],
            "scope": ["mcp"],
        }
        handler = _make_handler(path="/oauth/authorize", method="GET")
        captured_status: list[int] = []
        captured_headers: dict[str, str] = {}

        def fake_send_response(code: int) -> None:
            captured_status.append(code)

        def fake_send_header(name: str, value: str) -> None:
            captured_headers[name] = value

        def fake_end_headers() -> None:
            pass

        handler.send_response = fake_send_response
        handler.send_header = fake_send_header
        handler.end_headers = fake_end_headers
        handler._handle_oauth_authorize(params)

        self.assertEqual(captured_status, [302])
        location = captured_headers.get("Location", "")
        self.assertTrue(location.startswith(redirect_uri + "?"), location)
        parsed = urllib.parse.urlparse(location)
        qs = urllib.parse.parse_qs(parsed.query)
        code = qs["code"][0]
        self.assertEqual(qs["state"][0], "xyz")

        # token
        form = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }).encode("utf-8")
        token_handler = _make_handler(path="/oauth/token", body=form)
        token_captured: list = []
        token_handler._send = lambda status, payload, headers=None: token_captured.append((status, payload))

        token_handler.do_POST()

        self.assertEqual(token_captured[0][0], 200, token_captured)
        token_payload = token_captured[0][1]
        self.assertIn("access_token", token_payload)
        self.assertEqual(token_payload["token_type"], "Bearer")
        self.assertEqual(token_payload["scope"], "mcp")
        self.assertTrue(oauth_state.validate_access_token(token_payload["access_token"]))

    def test_authorize_rejects_unregistered_client(self) -> None:
        params = {
            "client_id": ["does-not-exist"],
            "redirect_uri": ["https://x.example/cb"],
            "response_type": ["code"],
            "code_challenge": ["a" * 43],
            "code_challenge_method": ["S256"],
        }
        handler = _make_handler(path="/oauth/authorize", method="GET")
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload))

        handler._handle_oauth_authorize(params)

        self.assertEqual(captured[0][0], 400)
        self.assertEqual(captured[0][1]["error"], "invalid_client")

    def test_authorize_rejects_redirect_uri_not_registered(self) -> None:
        client = self._register_client("https://allowed.example/cb")
        params = {
            "client_id": [client["client_id"]],
            "redirect_uri": ["https://other.example/cb"],
            "response_type": ["code"],
            "code_challenge": ["a" * 43],
            "code_challenge_method": ["S256"],
        }
        handler = _make_handler(path="/oauth/authorize", method="GET")
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload))

        handler._handle_oauth_authorize(params)

        self.assertEqual(captured[0][0], 400)
        self.assertEqual(captured[0][1]["error"], "invalid_request")

    def test_token_rejects_wrong_client_secret(self) -> None:
        client = self._register_client("https://x.example/cb")
        form = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": "irrelevant",
            "client_id": client["client_id"],
            "client_secret": "wrong-secret",
            "redirect_uri": "https://x.example/cb",
            "code_verifier": "verifier",
        }).encode("utf-8")
        handler = _make_handler(path="/oauth/token", body=form)
        captured: list = []
        handler._send = lambda status, payload, headers=None: captured.append((status, payload))

        handler.do_POST()

        self.assertEqual(captured[0][0], 401)
        self.assertEqual(captured[0][1]["error"], "invalid_client")

    # ---------- token persistence ----------

    def test_access_token_survives_simulated_restart(self) -> None:
        token, _ttl = oauth_state.issue_access_token(client_id="some-client", scope="mcp")
        self.assertTrue(oauth_state.validate_access_token(token))

        # Simulate process restart: drop in-memory state, keep the file on disk
        oauth_state._reload_token_store_for_tests()

        self.assertTrue(oauth_state.validate_access_token(token))
        self.assertTrue(self._token_store_path.exists())

    def test_expired_access_token_dropped_on_load(self) -> None:
        oauth_state.issue_access_token(client_id="some-client")
        # Force-expire all tokens on disk
        with oauth_state._LOCK:
            for entry in oauth_state._ACCESS_TOKENS.values():
                entry["expires_at"] = 0
            oauth_state._save_token_store()
        oauth_state._reload_token_store_for_tests()

        # validate triggers load + purge
        self.assertFalse(oauth_state.validate_access_token("anything"))
        self.assertEqual(oauth_state._ACCESS_TOKENS, {})

    def test_auth_code_survives_simulated_restart(self) -> None:
        verifier, challenge = _pkce_pair()
        code = oauth_state.issue_auth_code(
            client_id="some-client",
            redirect_uri="https://x.example/cb",
            code_challenge=challenge,
            code_challenge_method="S256",
            scope="mcp",
        )

        oauth_state._reload_token_store_for_tests()

        entry = oauth_state.consume_auth_code(
            code=code,
            client_id="some-client",
            redirect_uri="https://x.example/cb",
            code_verifier=verifier,
        )
        self.assertIsNotNone(entry)

    @unittest.skipIf(sys.platform == "win32", "POSIX permission semantics")
    def test_credential_stores_are_owner_only(self) -> None:
        self._register_client("https://x.example/cb")
        oauth_state.issue_access_token(client_id="some-client")

        for path in (self._store_path, self._token_store_path):
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(
                mode,
                0o600,
                f"{path.name} should be 0600, got {oct(mode)}",
            )

    def test_reset_clears_both_stores(self) -> None:
        self._register_client("https://x.example/cb")
        oauth_state.issue_access_token(client_id="some-client")
        self.assertTrue(self._store_path.exists())
        self.assertTrue(self._token_store_path.exists())

        oauth_state.reset_client_registry_for_tests()

        self.assertFalse(self._store_path.exists())
        self.assertFalse(self._token_store_path.exists())

    # ---------- backward compat: static env client ----------

    def test_static_env_client_still_works(self) -> None:
        os.environ["AGENTMEMORY_OAUTH_CLIENT_ID"] = "static-id"
        os.environ["AGENTMEMORY_OAUTH_CLIENT_SECRET"] = "static-secret"
        record = oauth_state.lookup_client("static-id")
        self.assertIsNotNone(record)
        self.assertTrue(oauth_state.verify_client_secret("static-id", "static-secret"))
        self.assertFalse(oauth_state.verify_client_secret("static-id", "nope"))
        # Static client has empty redirect_uris → any safe URI allowed (legacy).
        self.assertTrue(oauth_state.redirect_uri_allowed(record, "https://anything.example/cb"))
        self.assertFalse(oauth_state.redirect_uri_allowed(record, "http://evil.example/cb"))


if __name__ == "__main__":
    unittest.main()
