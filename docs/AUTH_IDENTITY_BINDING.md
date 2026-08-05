# Binding a request's scope to its credential

`AGENTMEMORY_ENFORCE_AUTH_USER_ID=1`

## The problem it addresses

Authentication answers *may this caller reach the API*. It has never answered
*whose memory may this caller touch*. `user_id` arrives in the request payload,
so a valid credential could name any scope:

```http
POST /v1/memories
Authorization: Bearer <a perfectly valid token>

{"text": "...", "user_id": "somebody-else"}
```

With a single owner this is invisible — there is only one scope, and naming it is
correct. With two, it is a cross-user read and write.

## What the mode does

When enabled **and** the presented credential carries a bound identity:

| Request | Result |
|---|---|
| `user_id` equals the bound id | passes through |
| `user_id` absent | filled in from the credential |
| `user_id` is some other value | refused, `ProviderIdentityError`, HTTP 403 |

Filling in the absent case is deliberate: a client should not have to repeat what
its token already states, and requiring it would push every caller into sending a
field they cannot be trusted with.

The check covers `add`, `search`, `search_page`, `list`, `list_page` and
`reconcile`. `get`, `update` and `delete` name a record by id and carry no scope,
so the record is read first and its own `user_id` is checked. Blocking writes
alone would leave reads open, and reads are the half that leaks.

The classification is total, and unclassified means refused. `list_scopes`,
`list_scopes_page`, `export` and `import` name no `user_id` and are not addressed
by record id — they range over the whole store — so a bound credential is refused
them outright rather than passed through for want of a listing. `health` is the
one explicit exemption, because it touches no user data. An operation added later
is refused until it is classified.

`/admin/*` is refused to a bound credential for the same reason. Those routes do
not dispatch through `OPERATIONS` — they call `runtime.admin`, which reaches the
provider directly — and there is no separate operator credential, so the same
bearer that reaches `/add` reaches `/admin/memories/<id>`. The admin surface is
built for an operator who is meant to see everything; scoping it to one identity
would be a second implementation of this check, so under enforcement a bound
credential simply does not get it.

It lives in one place — the wrapper `OperationSpec.__post_init__` installs around
every operation — because HTTP, MCP and CLI all dispatch through it. A per
transport check would mean the next transport arrives unguarded.

## Where a binding comes from

**AgentMemory does not authenticate end users.** There is no login; the authorize
endpoint learns the client, not the person. So a binding is configuration, never a
request parameter — a `bound_user_id` the caller could name would constrain
nobody:

```bash
export AGENTMEMORY_OAUTH_CLIENT_ID=my-client
export AGENTMEMORY_OAUTH_CLIENT_SECRET=...
export AGENTMEMORY_OAUTH_BOUND_USER_ID=alice
export AGENTMEMORY_ENFORCE_AUTH_USER_ID=1
```

A registered (DCR) client can carry the same field in its stored record, written
out of band by the operator.

The binding is stamped on the authorization code, carried into the issued token
pair, and preserved across refresh rotation. That last part matters: if refresh
dropped it, shedding the binding would cost one refresh call.

## What keeps working unchanged

- **Enforcement off** — the default. Nothing is checked, nothing is filled in,
  and `/admin/*`, `list_scopes`, `export` and `import` behave exactly as before.
- **A credential with no bound identity** — a static `AGENTMEMORY_API_TOKEN`, or an
  OAuth token issued before a binding was configured. It behaves exactly as
  before even with the flag on. Enforcing on unbound credentials would break
  every existing single-owner install on upgrade.
- **Anonymous local use** — unchanged.

## The boundary of the guarantee

This closes payload-supplied scope spoofing between holders of *different*
credentials. That is the whole of it.

It is **not** tenant isolation, and AgentMemory should not be described as
offering it. Specifically:

- A binding is only as trustworthy as whatever issued the token. AgentMemory
  cannot verify that the operator's configured `bound_user_id` corresponds to a
  real person, because it never sees one.
- **The mode is void unless every route to a token is bound.** Dynamic client
  registration is enabled by default and `/oauth/authorize` auto-approves, so
  anyone who can reach the server can register a client and mint a token that
  carries no binding — and unbound credentials are exempt by design. Turning this
  mode on is only meaningful together with `AGENTMEMORY_OAUTH_DISABLE_DCR=1` and
  a binding configured for every client that can obtain a token.
- In owner-process proxy mode the check runs in the process that received the
  request, and the proxy forwards under the owner's own (unbound) credential. The
  flag must therefore be set on the process clients talk to; setting it only on
  the owner process enforces nothing.
- Anyone who can read the token store can mint or edit bindings.
- `agent_id` and `run_id` are **not** bound. Requirement stated and deliberately
  not met: no evidenced need for it exists yet, and binding them would break
  legitimate multi-agent use under one identity.
- Providers are not partitioned. Records of different users share one store, and
  a provider bug or a direct read of the storage file crosses the line this check
  draws at the API.
- A record with no `user_id` is refused rather than assumed to be the caller's,
  so a store written without scopes must be scoped before the mode can be used
  on it. This is the main migration cost.

For the project's overall position see [SECURITY.md](../SECURITY.md) and
[RUNTIME_BOUNDARIES.md](RUNTIME_BOUNDARIES.md).
