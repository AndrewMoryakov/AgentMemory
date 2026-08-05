"""Binding a request's memory scope to the identity of the credential that made it.

Authentication answers "may this caller reach the API". It does not answer "whose
memory may this caller touch". Until this module existed the second question was
answered by the payload: `user_id` arrived from the client, so any holder of a
valid token could read or write any other user's scope by naming it. With one
owner that is invisible; with two it is a cross-tenant read.

The enforcement lives here and is applied in exactly one place —
`OperationSpec.__post_init__` in runtime/operations.py, through which every HTTP,
MCP and CLI call passes. Duplicating it per transport would mean a new transport
arrives unguarded, which is the usual way a check like this is lost.

Off by default. `AGENTMEMORY_ENFORCE_AUTH_USER_ID=1` turns it on, and it only
does anything when the credential actually carries a bound identity, so a static
API token keeps its existing behaviour.

**What this does not do.** AgentMemory does not authenticate end users: there is
no login, and the authorize endpoint takes the client's word for who it is. A
bound identity is therefore only as trustworthy as whatever issued the token —
the operator's configuration, or an upstream identity provider that AgentMemory
does not see. This closes payload-supplied scope spoofing between holders of
different tokens. It is not tenant isolation, and nothing here should be
described as such.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

from agentmemory.providers.base import ProviderIdentityError

# Operations whose scope is named directly by the caller.
SCOPED_OPERATIONS = frozenset({
    "add",
    "search",
    "search_page",
    "list",
    "list_page",
    "reconcile",
    "export",
})

# Operations that address one stored record by id. Their scope is whatever the
# record already carries, so it is resolved from storage rather than the payload.
RECORD_OPERATIONS = frozenset({"get", "update", "delete"})


@dataclass(frozen=True)
class AuthIdentity:
    """Who the presented credential says the caller is.

    `bound_user_id` is None for credentials that carry no identity — a static API
    token, or an OAuth token issued before a binding was configured. Those keep
    their existing unrestricted behaviour by design; enforcing on them would break
    every single-owner deployment on upgrade.
    """

    bound_user_id: str | None = None
    source: str = "none"


_ANONYMOUS = AuthIdentity()
_CURRENT: ContextVar[AuthIdentity] = ContextVar("agentmemory_auth_identity", default=_ANONYMOUS)


def enforcement_enabled() -> bool:
    return os.environ.get("AGENTMEMORY_ENFORCE_AUTH_USER_ID", "").strip() == "1"


def current_identity() -> AuthIdentity:
    return _CURRENT.get()


def set_identity(identity: AuthIdentity | None) -> None:
    """Set the identity for the current context. Transports call this once per
    request, including with None to clear a previous request's identity — the
    HTTP handler is reused across keep-alive requests on one connection, so a
    stale identity would otherwise leak from one request into the next."""
    _CURRENT.set(identity or _ANONYMOUS)


@contextmanager
def identity_scope(identity: AuthIdentity | None) -> Iterator[None]:
    token = _CURRENT.set(identity or _ANONYMOUS)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def _mismatch(bound: str, presented: str) -> ProviderIdentityError:
    # The bound id is the caller's own and safe to echo; the presented one is
    # theirs too. Neither reveals anything about the other tenant.
    return ProviderIdentityError(
        f"This credential is bound to user_id '{bound}' and cannot act on "
        f"user_id '{presented}'. Omit user_id to use the bound identity, or "
        f"unset AGENTMEMORY_ENFORCE_AUTH_USER_ID to disable enforcement."
    )


def enforce_scope(operation_name: str, source: dict[str, Any]) -> dict[str, Any]:
    """Return the source to execute, with the bound identity applied.

    A no-op unless enforcement is on and the credential carries an identity.
    When it applies:

    - a matching `user_id` passes through;
    - a missing `user_id` is filled in from the credential, so a client never has
      to repeat what the token already says;
    - a differing `user_id` raises ProviderIdentityError.
    """
    identity = current_identity()
    bound = identity.bound_user_id
    if not bound or not enforcement_enabled():
        return source
    if operation_name not in SCOPED_OPERATIONS:
        return source

    presented = source.get("user_id")
    if presented is None:
        return {**source, "user_id": bound}
    if presented != bound:
        raise _mismatch(bound, str(presented))
    return source


def enforce_record_scope(operation_name: str, record_user_id: Any) -> None:
    """Check a stored record's own scope against the bound identity.

    `get`, `update` and `delete` name a record by id and never carry a scope, so
    the only way to know whose record it is, is to look at the record. Callers
    resolve it and pass the value here.

    A record with no `user_id` is refused rather than allowed. It cannot be shown
    to belong to the caller, and under an explicitly enabled enforcement mode the
    safe reading of "unknown owner" is "not yours". This is why the mode is
    opt-in: a store written without scopes will need them before it can be turned
    on.
    """
    identity = current_identity()
    bound = identity.bound_user_id
    if not bound or not enforcement_enabled():
        return
    if operation_name not in RECORD_OPERATIONS:
        return

    if record_user_id is None:
        raise ProviderIdentityError(
            f"This record carries no user_id, so it cannot be shown to belong to "
            f"the bound identity '{bound}'. Records must be scoped before "
            f"AGENTMEMORY_ENFORCE_AUTH_USER_ID can be used with them."
        )
    if record_user_id != bound:
        raise _mismatch(bound, str(record_user_id))
