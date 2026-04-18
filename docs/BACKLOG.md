# Backlog — Known Bugs & Hygiene Items

Short, specific things that came out of diagnostics and operational work but
haven't been picked up yet. Strategic direction lives in `ROADMAP.md`; this
doc is for items small enough to land as a single PR each.

Format per entry:
- **Status** — `open` / `in-progress` / `blocked`
- **Severity** — `bug` (wrong behavior) / `hygiene` (right behavior, needs polish)
- **Why** — what the fix buys us
- **Where** — pointer to code / test location

---

## 1. `mcp.py` masks `KeyError` from tool execution as "Unknown tool"

- **Status:** open
- **Severity:** bug
- **Why:** When a client passes the wrong argument name to a tool, the
  `KeyError` raised from inside `OPERATIONS_BY_MCP_NAME[name].execute(source)`
  is caught by the outer `except KeyError` that was meant to handle "unknown
  tool name" lookups. The client sees
  `{"code": -32601, "message": "Unknown tool: memory_add"}` and reasonably
  concludes the tool doesn't exist. Bad DX and hides the real schema mismatch.

  Reproduced during the first diagnostic run (v1 report) by sending
  `memory_add` with `text` as `messages` (wrong field name). Surfaced as
  "Unknown tool" instead of a clear validation error.

- **Where:** `agentmemory/mcp.py` — `handle_request`, the `tools/call` branch:

  ```python
  try:
      return success(request_id, handle_call(name, arguments))
  except KeyError:
      return error(request_id, -32601, f"Unknown tool: {name}")
  ```

- **Fix outline:** resolve the tool BEFORE the try, return `-32601` only when
  the lookup itself returns `None`. Keep the inner execution in its own
  try/except for `ProviderError` and `Exception` paths that already exist.

  ```python
  spec = OPERATIONS_BY_MCP_NAME.get(name)
  if spec is None:
      return error(request_id, -32601, f"Unknown tool: {name}")
  try:
      return success(request_id, mcp_result(spec.execute(mcp_operation_source(name, arguments))))
  except ProviderError as exc:
      return success(request_id, error_result(exc))
  except Exception as exc:
      traceback.print_exc(file=sys.stderr)
      return success(request_id, mcp_result({"error_type": "InternalError", "message": str(exc)}, is_error=True))
  ```

- **Test to add:** `test_tools_call_with_bad_argument_surfaces_validation_not_unknown_tool`
  in `tests/test_agentmemory_mcp_server.py`.

---

## 2. No rate limiting on `/mcp` or `/oauth/token`

- **Status:** open
- **Severity:** bug (abuse risk)
- **Why:** Anyone with the bearer token (or a leaked OAuth client
  secret) can loop `memory_add` and drain OpenRouter budget. Today only the
  owner has the credentials, so the blast radius is self-inflicted — but any
  future sharing of a token (even for read-only use) inherits this risk.

  OpenRouter account limit is currently $2 with most of it remaining
  (see `GET /api/v1/key`). Cost per `memory_add` is fractions of a cent, so
  sustained abuse would take many minutes to matter — but those minutes are
  unsupervised.

- **Where:** `agentmemory/api.py` — in the bearer-auth path shared by `/mcp`,
  `/add`, `/search`, `/update`, `/memories`, `/admin/*`, and `/oauth/token`.

- **Fix outline:** in-process token bucket keyed by the bearer value (or OAuth
  client_id), 60 requests / minute default, override via
  `AGENTMEMORY_RATE_LIMIT_PER_MINUTE` env. 429 response on overrun with
  `Retry-After` header. No Redis dependency — in-memory fine for single-
  instance deployment, and the sliding window resets on restart which is
  acceptable for anti-abuse rather than quota enforcement.

- **Scope note:** `/health`, `/.well-known/oauth-*`, and `/oauth/authorize`
  stay unthrottled — they're either unauthenticated liveness or part of the
  discovery handshake that can burst legitimately.

---

## 3. Compose v2 network drift: root cause un-addressed

- **Status:** mitigated
- **Severity:** hygiene
- **Why:** `docker compose up -d --build --force-recreate` has been observed
  dropping `agentmemory` off the external `netbird_netbird` network even when
  `--force-recreate` is specified. Seen twice on this server (once on first
  deploy, once while verifying the post-remediation grammar fix). The same
  bug caused the 20-minute `tca-web` outage documented in
  `/opt/telegramchatanalyzer/POSTMORTEM_NETWORK_DETACH.md`.

  We ship `deploy/redeploy.sh` which forces the re-attach idempotently — the
  symptom is gone — but the root cause is still there and could bite any
  future service that joins `netbird_netbird`.

- **Where:** `deploy/docker-compose.yml` declares the external network
  correctly. The behavior is upstream in `docker compose` v2.

- **Fix outline:**
  1. File an upstream issue with a minimal reproducer (two networks, one
     external with an explicit `name:`, `up -d --force-recreate` dropping
     the external on the second invocation).
  2. Add a comment in `deploy/docker-compose.yml` pointing at the issue URL
     and at `deploy/redeploy.sh` so nobody removes the guard.
  3. If upstream fix lands, deprecate the self-heal in `redeploy.sh`.

---

## 4. No provider-neutral memory export/import

- **Status:** open
- **Severity:** hygiene
- **Why:** Memories currently live in a provider-shaped store (Qdrant for
  mem0, flat JSON for localjson). Migrating between providers or between
  embedding models requires manual work. Also means the backup produced by
  `deploy/backup-agentmemory.sh` is only restorable onto a compatible
  Qdrant + embedding-dimension combination — a change to either breaks the
  restore.

  An `export` tool that walks the scope inventory and emits a JSONL file of
  `MemoryRecord`s, plus an `import` that replays them via `memory_add`, would
  buy provider-neutral portability and make backup/restore independent of
  the storage layer.

- **Where:** new `agentmemory/runtime/portability.py` + MCP tools
  `memory_export` / `memory_import` + CLI wrappers.

- **Fix outline:** reuse `list_scopes` + per-scope `list_memories`. Export
  format: one JSON object per line with `id`, `memory`, `metadata`, scope
  fields, timestamps. Import: stream the file, batch-add via current
  `memory_add` path. `infer=false` on import to guarantee round-trip fidelity.
  Metadata gets a `source: "import"` tag for provenance.

---

## 5. Re-enable `infer=true` with observable rewrites — or commit to "never"

- **Status:** open
- **Severity:** hygiene (decision, not a bug)
- **Why:** DEFECT-04 was closed by flipping the default to `infer=false`. The
  mechanism for `infer=true` still works and returns `transformed`,
  `original_text`, `stored_text` — so the hostile silent rewrite is gone. But
  the feature is effectively invisible to users: nobody will discover it from
  the default.

  Two paths:
  1. Remove `infer=true` entirely. Commit to "the runtime stores what you
     sent, full stop". Simplest product story.
  2. Add an example in `docs/USE_CASES.md` or a dedicated doc showing
     `infer=true` for fact extraction (e.g. from chat transcripts) with the
     surfaced `transformed` metadata.

  Letting it sit in the middle — available but undocumented — is the worst
  of both worlds.

- **Where:** `agentmemory/runtime/operations.py` (schema + `_execute_add`) +
  docs.

---

## 6. Conflict detection / memory hygiene

- **Status:** open
- **Severity:** hygiene (feature gap)
- **Why:** Already have TTL and dedup-on-add. The next step in "real memory
  runtime, not just an append-only store" is detecting contradictory
  memories (A says X at t1, B says ¬X at t2) and surfacing them to callers
  so they can resolve. This is the differentiating feature vs. "mem0 behind
  HTTP".

  Out of scope for a single PR — proper fact reconciliation is a mini-product.
  Parked here as the flag for when it becomes a priority.

- **Where:** would live in a new `agentmemory/runtime/reconcile.py` with a
  dedicated MCP tool (`memory_reconcile` returning conflict pairs), and
  optional enforcement policy in `memory_add` (warn / reject / supersede).

---

## Closed (for reference)

- **DEFECT-01** — `rerank` not capability-aware: fixed in
  `agentmemory/runtime/transport.py::validate_and_build_search_kwargs`.
  Covered by tests in `tests/test_defect_fixes.py` and
  `tests/test_post_remediation.py`.
- **DEFECT-02** — PID/state files not populated under PID 1 in Docker: fixed
  in `agentmemory/api.py::_record_supervisor_files` + signal handlers.
- **DEFECT-03** — double-delete raising `ProviderUnavailableError`: fixed in
  `_execute_delete` (idempotent response) plus `Mem0Provider._map_exception`
  (message-pattern → `MemoryNotFoundError`).
- **DEFECT-04** — silent LLM rewrite on `memory_add`: fixed by flipping
  default to `infer=false` and surfacing `transformed`/`original_text`/
  `stored_text` when `infer=true` differs.
- **DEFECT-05** — mem0 contract advertising sentinels: fixed in
  `Mem0Provider.provider_contract` and `BaseMemoryProvider.provider_contract`.
