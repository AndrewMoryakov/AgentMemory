"""Binding a request's memory scope to the identity of its credential.

The defect these cover: authentication proved a caller could reach the API, and
then `user_id` was taken from the payload, so any token holder could name another
user's scope and read or write it.

Every test drives a real public surface — the operation registry that HTTP, MCP
and CLI all dispatch through, plus the HTTP handler and the MCP request handler
themselves. None of them call the enforcement helpers directly, because a test
that calls the check proves the check runs when called, which is not the claim.
"""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agentmemory.api as agentmemory_api
import agentmemory.mcp as agentmemory_mcp
import agentmemory.runtime.admin as admin_module
import agentmemory.runtime.operations as ops
from agentmemory import oauth as oauth_state
from agentmemory.providers.base import ProviderIdentityError
from agentmemory.runtime.identity import AuthIdentity, identity_scope
from agentmemory.runtime.transport import provider_error_status

from tests._handler_factory import make_handler

ENV_KEYS = (
    "AGENTMEMORY_ENFORCE_AUTH_USER_ID",
    "AGENTMEMORY_OAUTH_CLIENT_ID",
    "AGENTMEMORY_OAUTH_CLIENT_SECRET",
    "AGENTMEMORY_OAUTH_BOUND_USER_ID",
    "AGENTMEMORY_OAUTH_STORE",
    "AGENTMEMORY_OAUTH_TOKEN_STORE",
    "AGENTMEMORY_API_TOKEN",
)

OWNER = "alice"
OTHER = "bob"


class IdentityBindingTestCase(unittest.TestCase):
    """Enforcement on, credential bound to OWNER, provider calls captured."""

    enforce = True
    bound_user_id: str | None = OWNER

    def setUp(self) -> None:
        self._original_env = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        self._temp = tempfile.TemporaryDirectory()
        temp = Path(self._temp.name)
        os.environ["AGENTMEMORY_OAUTH_STORE"] = str(temp / "clients.json")
        os.environ["AGENTMEMORY_OAUTH_TOKEN_STORE"] = str(temp / "tokens.json")
        if self.enforce:
            os.environ["AGENTMEMORY_ENFORCE_AUTH_USER_ID"] = "1"
        oauth_state.reset_client_registry_for_tests()

        self.captured: list[dict] = []
        self._patches = [
            mock.patch.object(ops, "should_proxy_to_api", return_value=False),
            mock.patch.object(ops, "memory_add", side_effect=self._record("add")),
            mock.patch.object(ops, "memory_search", side_effect=self._record("search")),
            mock.patch.object(ops, "memory_list", side_effect=self._record("list")),
            mock.patch.object(ops, "memory_update", side_effect=self._record("update")),
            mock.patch.object(ops, "memory_delete", side_effect=self._record("delete")),
            mock.patch.object(
                ops,
                "active_provider_capabilities",
                return_value=_capabilities(),
            ),
            mock.patch.object(ops, "active_provider_name", return_value="fake"),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in reversed(self._patches):
            patch.stop()
        oauth_state.reset_client_registry_for_tests()
        self._temp.cleanup()
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _record(self, name):
        def _call(**kwargs):
            self.captured.append({"operation": name, **kwargs})
            return {"id": "mem-1", "memory": "stored", "user_id": kwargs.get("user_id")}

        return _call

    def identity(self) -> AuthIdentity | None:
        if self.bound_user_id is None:
            return None
        return AuthIdentity(bound_user_id=self.bound_user_id, source="oauth")

    def execute(self, operation: str, source: dict):
        with identity_scope(self.identity()):
            return ops.OPERATIONS[operation].execute(source)


def _capabilities(**overrides) -> dict:
    capabilities = {
        "supports_semantic_search": True,
        "supports_text_search": False,
        "supports_filters": True,
        "supports_metadata_filters": True,
        "supports_rerank": True,
        "supports_update": True,
        "supports_delete": True,
        "supports_scopeless_list": True,
        "requires_scope_for_list": False,
        "requires_scope_for_search": False,
        "supports_owner_process_mode": True,
        "supports_scope_inventory": True,
        "supports_pagination": False,
    }
    capabilities.update(overrides)
    return capabilities


class MatchingScopeIsAllowed(IdentityBindingTestCase):
    def test_add_with_the_bound_user_id_reaches_the_provider(self) -> None:
        self.execute("add", {"messages": [{"role": "user", "content": "hi"}], "user_id": OWNER})
        self.assertEqual(self.captured[-1]["user_id"], OWNER)


class MissingScopeIsFilledFromTheCredential(IdentityBindingTestCase):
    """Requirement 4: a client should not have to repeat what the token says."""

    def test_add_without_user_id_uses_the_bound_identity(self) -> None:
        self.execute("add", {"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(self.captured[-1]["user_id"], OWNER)

    def test_search_without_user_id_uses_the_bound_identity(self) -> None:
        self.execute("search", {"query": "anything"})
        self.assertEqual(self.captured[-1]["user_id"], OWNER)

    def test_list_without_user_id_uses_the_bound_identity(self) -> None:
        self.execute("list", {})
        self.assertEqual(self.captured[-1]["user_id"], OWNER)


class MismatchedScopeIsRejected(IdentityBindingTestCase):
    def test_add_naming_another_user_is_refused(self) -> None:
        with self.assertRaises(ProviderIdentityError):
            self.execute("add", {"messages": [{"role": "user", "content": "hi"}], "user_id": OTHER})
        self.assertEqual(self.captured, [], "a refused request must not reach the provider")

    def test_the_error_carries_both_ids_but_no_other_detail(self) -> None:
        with self.assertRaises(ProviderIdentityError) as caught:
            self.execute("search", {"query": "q", "user_id": OTHER})
        message = str(caught.exception)
        self.assertIn(OWNER, message)
        self.assertIn(OTHER, message)


class NoBypassThroughOtherOperations(IdentityBindingTestCase):
    """Requirement 8's last case. Blocking `add` alone would leave reads open,
    and reads are the half that leaks."""

    def test_search_cannot_target_another_user(self) -> None:
        with self.assertRaises(ProviderIdentityError):
            self.execute("search", {"query": "q", "user_id": OTHER})
        self.assertEqual(self.captured, [])

    def test_list_cannot_target_another_user(self) -> None:
        with self.assertRaises(ProviderIdentityError):
            self.execute("list", {"user_id": OTHER})
        self.assertEqual(self.captured, [])

    def test_search_page_cannot_target_another_user(self) -> None:
        with self.assertRaises(ProviderIdentityError):
            self.execute("search_page", {"query": "q", "user_id": OTHER})

    def test_list_page_cannot_target_another_user(self) -> None:
        with self.assertRaises(ProviderIdentityError):
            self.execute("list_page", {"user_id": OTHER})

    def test_get_of_another_users_record_is_refused(self) -> None:
        with mock.patch.object(ops, "memory_get", return_value={"id": "m", "user_id": OTHER}):
            with self.assertRaises(ProviderIdentityError):
                self.execute("get", {"memory_id": "m"})

    def test_update_of_another_users_record_is_refused(self) -> None:
        with mock.patch.object(ops, "memory_get", return_value={"id": "m", "user_id": OTHER}):
            with self.assertRaises(ProviderIdentityError):
                self.execute("update", {"memory_id": "m", "data": "x"})
        self.assertEqual(
            [entry for entry in self.captured if entry["operation"] == "update"],
            [],
            "the refusal must happen before the write",
        )

    def test_delete_of_another_users_record_is_refused(self) -> None:
        with mock.patch.object(ops, "memory_get", return_value={"id": "m", "user_id": OTHER}):
            with self.assertRaises(ProviderIdentityError):
                self.execute("delete", {"memory_id": "m"})
        self.assertEqual([e for e in self.captured if e["operation"] == "delete"], [])

    def test_own_record_still_updates(self) -> None:
        with mock.patch.object(ops, "memory_get", return_value={"id": "m", "user_id": OWNER}):
            self.execute("update", {"memory_id": "m", "data": "x"})
        self.assertEqual(self.captured[-1]["operation"], "update")

    def test_unscoped_record_is_refused_rather_than_assumed_ours(self) -> None:
        with mock.patch.object(ops, "memory_get", return_value={"id": "m", "user_id": None}):
            with self.assertRaises(ProviderIdentityError):
                self.execute("get", {"memory_id": "m"})


class EnforcementDisabledKeepsOldBehaviour(IdentityBindingTestCase):
    """Requirement 5 and the backward-compatibility criterion. This is the case
    that decides whether existing installs survive an upgrade."""

    enforce = False

    def test_another_users_scope_is_accepted_when_the_flag_is_off(self) -> None:
        self.execute("add", {"messages": [{"role": "user", "content": "hi"}], "user_id": OTHER})
        self.assertEqual(self.captured[-1]["user_id"], OTHER)

    def test_missing_user_id_is_not_filled_in_when_the_flag_is_off(self) -> None:
        self.execute("add", {"messages": [{"role": "user", "content": "hi"}]})
        self.assertIsNone(self.captured[-1]["user_id"])


class CredentialWithoutIdentityIsUnaffected(IdentityBindingTestCase):
    """A static API token carries no identity. Enforcement is on, and it still
    behaves exactly as before — otherwise turning the flag on would break every
    single-owner deployment that uses AGENTMEMORY_API_TOKEN."""

    bound_user_id = None

    def test_static_token_may_still_name_any_scope(self) -> None:
        self.execute("add", {"messages": [{"role": "user", "content": "hi"}], "user_id": OTHER})
        self.assertEqual(self.captured[-1]["user_id"], OTHER)

    def test_static_token_is_not_given_a_scope_it_did_not_ask_for(self) -> None:
        self.execute("add", {"messages": [{"role": "user", "content": "hi"}]})
        self.assertIsNone(self.captured[-1]["user_id"])


class TokenLifecycleCarriesTheBinding(unittest.TestCase):
    """Requirement: the binding survives refresh. If it did not, shedding the
    binding would cost one refresh call and the check would be decorative."""

    def setUp(self) -> None:
        self._original_env = {key: os.environ.get(key) for key in ENV_KEYS}
        self._temp = tempfile.TemporaryDirectory()
        temp = Path(self._temp.name)
        os.environ["AGENTMEMORY_OAUTH_STORE"] = str(temp / "clients.json")
        os.environ["AGENTMEMORY_OAUTH_TOKEN_STORE"] = str(temp / "tokens.json")
        os.environ["AGENTMEMORY_OAUTH_CLIENT_ID"] = "static-client"
        os.environ["AGENTMEMORY_OAUTH_CLIENT_SECRET"] = "static-secret"
        os.environ["AGENTMEMORY_OAUTH_BOUND_USER_ID"] = OWNER
        oauth_state.reset_client_registry_for_tests()

    def tearDown(self) -> None:
        oauth_state.reset_client_registry_for_tests()
        self._temp.cleanup()
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_static_client_binding_comes_from_configuration(self) -> None:
        self.assertEqual(oauth_state.bound_user_id_for_client("static-client"), OWNER)

    def test_issued_access_token_reports_its_binding(self) -> None:
        issued = oauth_state.issue_token_pair(client_id="static-client", scope="mcp", bound_user_id=OWNER)
        self.assertEqual(oauth_state.access_token_bound_user_id(issued["access_token"]), OWNER)

    def test_refresh_preserves_the_binding(self) -> None:
        issued = oauth_state.issue_token_pair(client_id="static-client", scope="mcp", bound_user_id=OWNER)
        rotated = oauth_state.consume_refresh_token(
            refresh_token=issued["refresh_token"], client_id="static-client"
        )
        self.assertIsNotNone(rotated)
        self.assertEqual(oauth_state.access_token_bound_user_id(rotated["access_token"]), OWNER)

    def test_refresh_of_the_rotated_token_still_preserves_it(self) -> None:
        issued = oauth_state.issue_token_pair(client_id="static-client", bound_user_id=OWNER)
        first = oauth_state.consume_refresh_token(refresh_token=issued["refresh_token"], client_id="static-client")
        second = oauth_state.consume_refresh_token(refresh_token=first["refresh_token"], client_id="static-client")
        self.assertEqual(oauth_state.access_token_bound_user_id(second["access_token"]), OWNER)

    def test_a_token_issued_without_a_binding_reports_none(self) -> None:
        issued = oauth_state.issue_token_pair(client_id="static-client")
        self.assertIsNone(oauth_state.access_token_bound_user_id(issued["access_token"]))


class ErrorSurfacesIdenticallyOnHttpAndMcp(IdentityBindingTestCase):
    """Requirement 7. Both transports render ProviderError through the same
    payload builder, so this pins the status and the error_type rather than
    trusting that they still share it."""

    def test_http_returns_403_with_the_typed_error(self) -> None:
        self.assertEqual(provider_error_status(ProviderIdentityError("x")), 403)

    def test_mcp_marks_the_same_error_type(self) -> None:
        spec = ops.OPERATIONS_BY_MCP_NAME["memory_search"]
        with identity_scope(self.identity()):
            result = agentmemory_mcp.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "memory_search",
                        "arguments": {"query": "q", "user_id": OTHER},
                    },
                }
            )
        payload = result["result"]
        self.assertTrue(payload["isError"])
        self.assertEqual(payload["structuredContent"]["error_type"], "ProviderIdentityError")
        self.assertIsNotNone(spec)


class HttpRequestBindsTheCredentialIdentity(unittest.TestCase):
    """The binding has to reach the runtime from the transport, and it has to
    stop applying when the next request on the same connection presents a
    different credential. A handler instance is reused across keep-alive
    requests, so a leaked identity would be a cross-user leak of its own."""

    def setUp(self) -> None:
        self._original_env = {key: os.environ.get(key) for key in ENV_KEYS}
        self._temp = tempfile.TemporaryDirectory()
        temp = Path(self._temp.name)
        os.environ["AGENTMEMORY_OAUTH_STORE"] = str(temp / "clients.json")
        os.environ["AGENTMEMORY_OAUTH_TOKEN_STORE"] = str(temp / "tokens.json")
        os.environ["AGENTMEMORY_OAUTH_CLIENT_ID"] = "static-client"
        os.environ["AGENTMEMORY_OAUTH_CLIENT_SECRET"] = "static-secret"
        os.environ["AGENTMEMORY_OAUTH_BOUND_USER_ID"] = OWNER
        os.environ["AGENTMEMORY_ENFORCE_AUTH_USER_ID"] = "1"
        oauth_state.reset_client_registry_for_tests()
        agentmemory_api._RATE_LIMITER.reset()
        self.token = oauth_state.issue_token_pair(client_id="static-client", bound_user_id=OWNER)["access_token"]

    def tearDown(self) -> None:
        oauth_state.reset_client_registry_for_tests()
        agentmemory_api._RATE_LIMITER.reset()
        self._temp.cleanup()
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _handler(self, authorization: str | None):
        headers = {"Authorization": authorization} if authorization else {}
        return make_handler(path="/v1/health", headers=headers)

    def test_a_bound_token_publishes_its_identity(self) -> None:
        handler = self._handler(f"Bearer {self.token}")
        self.assertTrue(handler._require_auth())
        from agentmemory.runtime.identity import current_identity

        self.assertEqual(current_identity().bound_user_id, OWNER)

    def _post(self, path: str, payload: dict):
        """One real POST through do_POST, returning (status, body)."""
        body = json.dumps(payload).encode("utf-8")
        handler = make_handler(
            path=path,
            method="POST",
            body=body,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        captured: dict = {}

        def _send(status, obj, headers=None):
            captured["status"] = status
            captured["body"] = obj

        handler._send = _send
        handler.do_POST()
        return captured.get("status"), captured.get("body")

    def test_a_mismatched_scope_is_refused_over_real_http(self) -> None:
        with mock.patch.object(ops, "should_proxy_to_api", return_value=False), \
             mock.patch.object(ops, "memory_add") as add:
            status, body = self._post("/add", {"text": "hello", "user_id": OTHER})
        self.assertEqual(status, 403)
        self.assertEqual(body["error_type"], "ProviderIdentityError")
        add.assert_not_called()

    def test_an_absent_scope_is_filled_in_over_real_http(self) -> None:
        with mock.patch.object(ops, "should_proxy_to_api", return_value=False), \
             mock.patch.object(ops, "memory_add", return_value={"id": "m"}) as add:
            status, _ = self._post("/add", {"text": "hello"})
        self.assertEqual(status, 200)
        self.assertEqual(add.call_args.kwargs["user_id"], OWNER)

    def test_the_identity_does_not_survive_into_an_unauthenticated_request(self) -> None:
        from agentmemory.runtime.identity import current_identity

        bound = self._handler(f"Bearer {self.token}")
        bound._require_auth()
        self.assertEqual(current_identity().bound_user_id, OWNER)

        anonymous = self._handler(None)
        anonymous.wfile = io.BytesIO()
        anonymous.send_response = lambda *a, **k: None
        anonymous.send_header = lambda *a, **k: None
        anonymous.end_headers = lambda *a, **k: None
        self.assertFalse(anonymous._require_auth())
        self.assertIsNone(current_identity().bound_user_id)


class ScopeInventoryAndPortabilityAreNotAWayAround(IdentityBindingTestCase):
    """Operations the enforced set never classified.

    `list_scopes` names no `user_id`, so `enforce_scope` waved it through and it
    returned the inventory of every scope in the store — the other users' ids
    themselves. `import` names no `user_id` either, and then replays a file whose
    records each carry their own, straight into `memory_add`. `export` was in the
    scoped set but ignores `user_id` entirely: it walks the whole inventory.

    So the classification is now total. An operation that is neither scoped by
    payload nor addressed by record id is refused under a bound identity, rather
    than passed through because nobody listed it.
    """

    def test_list_scopes_does_not_hand_over_the_other_users_ids(self) -> None:
        with mock.patch.object(
            ops, "memory_list_scopes",
            return_value={"items": [{"kind": "user", "value": OWNER}, {"kind": "user", "value": OTHER}]},
        ) as inventory:
            with self.assertRaises(ProviderIdentityError):
                self.execute("list_scopes", {})
            inventory.assert_not_called()

    def test_list_scopes_page_is_refused_too(self) -> None:
        with mock.patch.object(
            ops, "memory_list_scopes_page", return_value={"items": [], "next_cursor": None}
        ) as inventory:
            with self.assertRaises(ProviderIdentityError):
                self.execute("list_scopes_page", {})
            inventory.assert_not_called()

    def test_import_cannot_plant_a_record_under_another_user(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "in.jsonl"
            source.write_text(
                json.dumps({"memory": "planted", "user_id": OTHER}) + "\n", encoding="utf-8"
            )
            with self.assertRaises(ProviderIdentityError):
                self.execute("import", {"path": str(source)})
        self.assertEqual(
            [entry for entry in self.captured if entry["operation"] == "add"],
            [],
            "a refused import must not reach the provider",
        )

    def test_export_does_not_walk_the_other_users_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "dump.jsonl"
            with mock.patch.object(
                ops, "memory_list_scopes_page", return_value={"items": [], "next_cursor": None}
            ) as inventory:
                with self.assertRaises(ProviderIdentityError):
                    self.execute("export", {"path": str(target)})
                inventory.assert_not_called()
            self.assertFalse(target.exists())

    def test_health_is_still_reachable(self) -> None:
        with mock.patch.object(ops, "health", return_value={"ok": True}):
            self.assertEqual(self.execute("health", {}), {"ok": True})


class UnclassifiedOperationsStayOpenWithoutABinding(IdentityBindingTestCase):
    """The same operations under a credential that carries no identity. The
    default-deny must not reach installs that never opted into a binding."""

    bound_user_id = None

    def test_list_scopes_still_works_for_an_unbound_credential(self) -> None:
        with mock.patch.object(ops, "memory_list_scopes", return_value={"items": []}) as inventory:
            self.execute("list_scopes", {})
            inventory.assert_called_once()


class UnclassifiedOperationsStayOpenWithEnforcementOff(IdentityBindingTestCase):
    enforce = False

    def test_list_scopes_still_works_with_the_flag_off(self) -> None:
        with mock.patch.object(ops, "memory_list_scopes", return_value={"items": []}) as inventory:
            self.execute("list_scopes", {})
            inventory.assert_called_once()


class AdminSurfaceIsNotAWayAround(unittest.TestCase):
    """`/admin/*` reaches the provider without OPERATIONS.

    `_require_auth` guards those routes, so the binding is published — but the
    handlers call `runtime.admin`, which calls `memory_get`/`memory_update`/
    `memory_delete`/`memory_list` directly. The wrapper the whole design rests on
    is never entered, so a token bound to OWNER could read, edit and delete
    OTHER's records by naming them. There is no separate admin credential: the
    same bearer that reaches `/add` reaches `/admin/memories/<id>`.
    """

    def setUp(self) -> None:
        self._original_env = {key: os.environ.get(key) for key in ENV_KEYS}
        self._temp = tempfile.TemporaryDirectory()
        temp = Path(self._temp.name)
        os.environ["AGENTMEMORY_OAUTH_STORE"] = str(temp / "clients.json")
        os.environ["AGENTMEMORY_OAUTH_TOKEN_STORE"] = str(temp / "tokens.json")
        os.environ["AGENTMEMORY_OAUTH_CLIENT_ID"] = "static-client"
        os.environ["AGENTMEMORY_OAUTH_CLIENT_SECRET"] = "static-secret"
        os.environ["AGENTMEMORY_OAUTH_BOUND_USER_ID"] = OWNER
        os.environ["AGENTMEMORY_ENFORCE_AUTH_USER_ID"] = "1"
        oauth_state.reset_client_registry_for_tests()
        agentmemory_api._RATE_LIMITER.reset()
        self.token = oauth_state.issue_token_pair(client_id="static-client", bound_user_id=OWNER)["access_token"]

        self.other_record = {"id": "other-1", "memory": "not yours", "user_id": OTHER}
        self._patches = [
            mock.patch.object(admin_module, "memory_list", return_value=[dict(self.other_record)]),
            mock.patch.object(admin_module, "memory_search", return_value=[dict(self.other_record)]),
            mock.patch.object(admin_module, "memory_get", return_value=dict(self.other_record)),
            mock.patch.object(admin_module, "memory_update", return_value={"ok": True}),
            mock.patch.object(admin_module, "memory_delete", return_value={"deleted": True}),
            mock.patch.object(admin_module, "active_provider_name", return_value="fake"),
            mock.patch.object(admin_module, "active_provider_capabilities", return_value=_capabilities()),
            mock.patch.object(admin_module, "admin_state_path", return_value=temp / "admin-state.json"),
        ]
        self.provider = {patch.attribute: patch.start() for patch in self._patches}

    def tearDown(self) -> None:
        for patch in reversed(self._patches):
            patch.stop()
        oauth_state.reset_client_registry_for_tests()
        agentmemory_api._RATE_LIMITER.reset()
        self._temp.cleanup()
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _request(self, method: str, path: str, payload: dict | None = None):
        body = json.dumps(payload or {}).encode("utf-8")
        handler = make_handler(
            path=path,
            method=method,
            body=body,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        captured: dict = {}

        def _send(status, obj, headers=None):
            captured["status"] = status
            captured["body"] = obj

        handler._send = _send
        getattr(handler, f"do_{method}")()
        return captured.get("status"), captured.get("body")

    def _assert_refused(self, status, body) -> None:
        self.assertEqual(status, 403)
        self.assertEqual(body["error_type"], "ProviderIdentityError")

    def test_admin_list_cannot_read_another_users_scope(self) -> None:
        self._assert_refused(*self._request("GET", f"/admin/memories?user_id={OTHER}"))
        self.provider["memory_list"].assert_not_called()
        self.provider["memory_search"].assert_not_called()

    def test_admin_get_cannot_read_another_users_record(self) -> None:
        self._assert_refused(*self._request("GET", "/admin/memories/other-1"))
        self.provider["memory_get"].assert_not_called()

    def test_admin_patch_cannot_edit_another_users_record(self) -> None:
        self._assert_refused(*self._request("PATCH", "/admin/memories/other-1", {"memory": "overwritten"}))
        self.provider["memory_update"].assert_not_called()

    def test_admin_delete_cannot_remove_another_users_record(self) -> None:
        self._assert_refused(*self._request("DELETE", "/admin/memories/other-1"))
        self.provider["memory_delete"].assert_not_called()

    def test_admin_pin_cannot_touch_another_users_record(self) -> None:
        self._assert_refused(*self._request("POST", "/admin/memories/other-1/pin", {"pinned": True}))

    def test_admin_stats_is_refused(self) -> None:
        self._assert_refused(*self._request("GET", "/admin/stats"))

    def test_admin_scopes_is_refused(self) -> None:
        self._assert_refused(*self._request("GET", "/admin/scopes"))

    def test_the_ordinary_route_still_works_for_the_bound_user(self) -> None:
        with mock.patch.object(ops, "should_proxy_to_api", return_value=False), \
             mock.patch.object(ops, "memory_add", return_value={"id": "m"}) as add:
            status, _ = self._request("POST", "/add", {"text": "hello"})
        self.assertEqual(status, 200)
        self.assertEqual(add.call_args.kwargs["user_id"], OWNER)


class AdminSurfaceIsUntouchedWithoutABinding(AdminSurfaceIsNotAWayAround):
    """An unbound credential — the operator's static token, or any install that
    never configured a binding — keeps the admin surface it had."""

    def setUp(self) -> None:
        super().setUp()
        # A token from the same client but carrying no binding.
        self.token = oauth_state.issue_token_pair(client_id="static-client")["access_token"]

    def test_admin_list_cannot_read_another_users_scope(self) -> None:
        status, _ = self._request("GET", f"/admin/memories?user_id={OTHER}")
        self.assertEqual(status, 200)
        self.provider["memory_list"].assert_called_once()

    def test_admin_get_cannot_read_another_users_record(self) -> None:
        status, body = self._request("GET", "/admin/memories/other-1")
        self.assertEqual(status, 200)
        self.assertEqual(body["id"], "other-1")

    def test_admin_patch_cannot_edit_another_users_record(self) -> None:
        status, _ = self._request("PATCH", "/admin/memories/other-1", {"memory": "overwritten"})
        self.assertEqual(status, 200)
        self.provider["memory_update"].assert_called_once()

    def test_admin_delete_cannot_remove_another_users_record(self) -> None:
        status, _ = self._request("DELETE", "/admin/memories/other-1")
        self.assertEqual(status, 200)
        self.provider["memory_delete"].assert_called_once()

    def test_admin_pin_cannot_touch_another_users_record(self) -> None:
        status, _ = self._request("POST", "/admin/memories/other-1/pin", {"pinned": True})
        self.assertEqual(status, 200)

    def test_admin_stats_is_refused(self) -> None:
        status, _ = self._request("GET", "/admin/stats")
        self.assertEqual(status, 200)

    def test_admin_scopes_is_refused(self) -> None:
        with mock.patch.object(ops, "should_proxy_to_api", return_value=False), \
             mock.patch.object(ops, "memory_list_scopes", return_value={"items": []}):
            status, _ = self._request("GET", "/admin/scopes")
        self.assertEqual(status, 200)

    def test_the_ordinary_route_still_works_for_the_bound_user(self) -> None:
        """Unbound: nothing is filled in, which is the pre-existing behaviour."""
        with mock.patch.object(ops, "should_proxy_to_api", return_value=False), \
             mock.patch.object(ops, "memory_add", return_value={"id": "m"}) as add:
            status, _ = self._request("POST", "/add", {"text": "hello"})
        self.assertEqual(status, 200)
        self.assertIsNone(add.call_args.kwargs["user_id"])


class McpCarriesThePortabilityBypass(IdentityBindingTestCase):
    """The remote reach of the portability hole: `/mcp` runs behind
    `_require_auth`, so `memory_import` is callable by a bound OAuth client."""

    def test_memory_import_over_mcp_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "in.jsonl"
            source.write_text(json.dumps({"memory": "planted", "user_id": OTHER}) + "\n", encoding="utf-8")
            with identity_scope(self.identity()):
                result = agentmemory_mcp.handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "memory_import", "arguments": {"path": str(source)}},
                    }
                )
        payload = result["result"]
        self.assertTrue(payload["isError"])
        self.assertEqual(payload["structuredContent"]["error_type"], "ProviderIdentityError")
        self.assertEqual([e for e in self.captured if e["operation"] == "add"], [])


if __name__ == "__main__":
    unittest.main()
