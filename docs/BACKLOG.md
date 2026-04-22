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

- **Status:** closed
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

- **Fix:** `tools/call` now resolves the tool before execution and returns
  `-32601` only when the tool name is unknown. Bad arguments are validated
  against the published schema and returned as structured
  `ProviderValidationError` tool errors instead of JSON-RPC unknown-tool
  errors.

---

## 2. No rate limiting on `/mcp` or `/oauth/token`

- **Status:** closed
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

- **Fix:** `agentmemory/api.py` now enforces an in-process token bucket keyed
  by the presented bearer token for authenticated API requests and by OAuth
  `client_id` for `/oauth/token`. The default is 60 requests / minute,
  overridable via `AGENTMEMORY_RATE_LIMIT_PER_MINUTE`. Overrun returns `429`
  with a `Retry-After` header. `/health`, `/.well-known/oauth-*`, and
  `/oauth/authorize` remain unthrottled. `tests/test_agentmemory_api.py`
  covers both bearer-auth and OAuth token-exchange rate limiting.

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

- **Status:** closed
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

## 7. Internal owner-process proxy requests do not propagate API auth

- **Status:** closed
- **Severity:** bug
- **Why:** When `AGENTMEMORY_API_TOKEN` or OAuth is enabled, the public HTTP API
  correctly requires a bearer token for `/add`, `/search`, `/memories`,
  `/admin/scopes`, and other protected operations. Non-owner processes that use
  an `owner_process_proxy` provider call those same endpoints through
  `agentmemory/runtime/http_client.py`, but the internal client does not send an
  `Authorization` header. `/health` can still return `{"ok": true}` without
  auth, so readiness can look healthy while real memory operations fail with
  401.

- **Where:** `agentmemory/runtime/http_client.py::_request`.

- **Fix:** `agentmemory/runtime/http_client.py::_request` now propagates
  `AGENTMEMORY_API_TOKEN` as a bearer token for internal proxy requests.
  `tests/test_agentmemory_http_client.py` covers every current `proxy_*`
  method with auth enabled so future endpoint additions do not silently regress.

---

## 8. `localjson` direct transport is not multi-process safe

- **Status:** closed
- **Severity:** bug
- **Why:** `LocalJsonProvider` advertises direct transport and protects
  read/modify/write with only an in-process `threading.Lock`. If CLI, MCP, and
  API processes write the same JSON file concurrently, each process has its own
  lock. Updates can be lost, and readers can observe partially written files.
  This undermines the shared local runtime story for the default evaluation
  provider.

- **Where:** `agentmemory/providers/localjson.py` — `_load`, `_save`, and
  `runtime_policy`.

- **Fix:** `LocalJsonProvider` now wraps file reads/writes with a cross-process
  lock file and writes through a temp file followed by `os.replace`. The direct
  transport policy remains valid because the provider no longer relies only on
  an in-process lock. `tests/test_localjson_provider.py` covers concurrent
  writes from separate Python processes.

---

## 9. Root Docker Compose can expose an unauthenticated API

- **Status:** closed
- **Severity:** bug (security footgun)
- **Why:** The deployment compose requires `AGENTMEMORY_API_TOKEN`, but the
  root `docker-compose.yml` binds the API to `0.0.0.0`, publishes the port, and
  does not require or set an API token. A user who starts the root compose can
  expose the memory API on the host without authentication.

- **Where:** `docker-compose.yml`.

- **Fix:** root `docker-compose.yml` now requires a non-empty
  `AGENTMEMORY_API_TOKEN` and binds the published host port to `127.0.0.1` by
  default. External exposure requires an explicit `AGENTMEMORY_BIND_ADDR`
  override, with bearer auth still enabled.

---

## 10. CLI `memory_add` still defaults to `infer=true`

- **Status:** closed
- **Severity:** bug
- **Why:** DEFECT-04 flipped the runtime default to `infer=false`, but the CLI
  adapter still maps add requests as `infer = not args.no_infer`. That means the
  CLI silently opts into provider-side rewriting unless callers remember to pass
  `--no-infer`, which contradicts the "store exactly what was sent unless
  explicitly requested" direction.

- **Where:** `agentmemory/runtime/operation_adapters.py::cli_operation_source`.

- **Fix:** `agentmemory ops_cli add` now exposes `--infer` as explicit opt-in
  and defaults to `infer=false`. The old `--no-infer` flag is retained as a
  hidden no-op for compatibility with scripts that already pass it.

---

## 11. MCP schemas are advertised but not enforced server-side

- **Status:** closed
- **Severity:** bug
- **Why:** MCP tools expose `inputSchema`, but `tools/call` sends arguments
  directly into `mcp_operation_source` without a validation step. Bad payloads
  therefore become Python exceptions such as `KeyError` instead of structured
  validation errors. This compounds the existing "Unknown tool" masking issue.

- **Where:** `agentmemory/mcp.py` and
  `agentmemory/runtime/operation_adapters.py::mcp_operation_source`.

- **Fix:** `agentmemory/mcp.py` now validates tool arguments against each
  operation's published schema before adapter/execution. Required fields,
  unknown fields, basic type mismatches, enum values, and integer/number
  minimums return structured `ProviderValidationError` tool results.

---

## 12. mem0 scope inventory depends on private Qdrant pickle internals

- **Status:** closed
- **Severity:** bug
- **Why:** `Mem0Provider.list_scopes` opens Qdrant's `storage.sqlite`, reads
  rows from the private `points` table, and calls `pickle.loads` on point blobs
  to recover payloads. This is version-coupled to Qdrant/mem0 internals and is
  unsafe if the storage file is ever attacker-controlled.

- **Where:** `agentmemory/providers/mem0.py::_iter_scope_payloads` and
  `list_scopes`.

- **Fix:** `list_scopes` now reads from an AgentMemory-owned SQLite scope
  registry shared across providers. `mem0` and `localjson` update the registry
  on add/update/delete, and legacy `mem0` installs can be migrated with the
  explicit `agentmemory rebuild-scope-registry` command. The old Qdrant
  `pickle` reader remains only as the one-shot rebuild seed path, not a runtime
  inventory dependency.

---

## 13. API handler tests depend on local auth environment

- **Status:** closed
- **Severity:** bug
- **Why:** API tests instantiate `BaseHTTPRequestHandler` manually via
  `Handler.__new__` and do not isolate `AGENTMEMORY_API_TOKEN` or OAuth env
  loaded from a local `.env`. With auth enabled, `_require_auth` calls
  `send_response` on a fake handler missing fields such as `requestline`,
  producing unrelated test failures.

- **Where:** `tests/test_agentmemory_api.py`.

- **Fix:** `tests/test_agentmemory_api.py` now clears API token and OAuth env
  around each test, restores the caller's environment in `tearDown`, and covers
  both `/health` modes explicitly: public liveness without auth and
  registry-backed health when an auth header is present.

---

## 14. `OPENROUTER_API_KEY` leaks into process-wide `os.environ`

- **Status:** closed
- **Severity:** bug (secret handling)
- **Why:** `Mem0Provider._load_memory` calls
  `os.environ.setdefault("OPENAI_API_KEY", api_key)` and the same for
  `OPENAI_BASE_URL`. The key is already threaded into `config["llm"]` and
  `config["embedder"]` a few lines below, so the environment mutation is
  redundant, but the side effect is real — any child process spawned after
  `_load_memory` runs (for example, MCP clients launched by `connect-clients`
  or the sweeper thread's downstream helpers) inherits the key, and any
  library in the same process that reads `OPENAI_API_KEY` now sees it.

- **Where:** `agentmemory/providers/mem0.py::_load_memory` (≈ L260).

- **Fix:** `Mem0Provider._load_memory` no longer writes `OPENAI_API_KEY` or
  `OPENAI_BASE_URL` into process-wide `os.environ`. The OpenRouter key is
  passed explicitly into both `llm.config.api_key` and
  `embedder.config.api_key` before `Memory.from_config`.

---

## 15. CLI onboarding passes OpenRouter key through argv

- **Status:** closed
- **Severity:** bug (secret handling)
- **Why:** `run_onboarding` calls
  `run_command(['configure', '--openrouter-api-key', key])`. The key lands in
  `argv`, which is visible in `ps aux`, Windows Task Manager's command-line
  column, shell history, CI job logs, and most process auditors.

- **Where:** `agentmemory/interactive.py::run_onboarding` and the
  `configure` command in `agentmemory/cli.py`.

- **Fix:** `configure` now supports `--openrouter-api-key-stdin` and
  `--openrouter-api-key-env NAME` in addition to the legacy argv form.
  `run_onboarding` now passes the prompted key through the stdin variant, so
  the secret no longer appears in the onboarding command argv. Tests cover the
  stdin/env provider paths and assert onboarding does not include the key in
  argv.

---

## 16. `filter_unexpired` silently violates the `limit` contract

- **Status:** closed
- **Severity:** bug
- **Why:** `_execute_search` and `_execute_list` apply
  `lifecycle_module.filter_unexpired` to the list returned by the provider
  after `limit` has already capped it. If the caller asked for `limit=10`
  and half the top-10 are TTL-expired, the caller receives 5 items and
  cannot distinguish "no more data" from "more data exists but it was
  filtered". Pagination and top-k semantics quietly break.

- **Where:** `agentmemory/runtime/operations.py` — `_execute_search`
  (≈ L198) and `_execute_list`.

- **Fix:** runtime `search` and `list` now retry with a larger provider
  `limit` when TTL filtering removes items from the first batch. This keeps the
  observable `limit` contract intact when more live records exist, while
  bounding retries so the refill path cannot loop forever. Regression tests
  cover both list and search refill behavior.

---

## 17. `proxy_add` / `proxy_search` defaults drift from runtime defaults

- **Status:** closed
- **Severity:** bug (regression risk)
- **Why:** `http_client.proxy_add` has `infer=True` as its default and
  `proxy_search` has `rerank=True`. The project-wide defaults were flipped
  to `infer=False` in DEFECT-04, and `rerank` is provider-capability-gated.
  All current call sites pass kwargs explicitly, so the defaults are inert
  today — but any future direct caller of `proxy_*` gets the pre-DEFECT-04
  behavior silently. This is exactly the footgun DEFECT-04 was meant to
  remove.

- **Where:** `agentmemory/runtime/http_client.py::proxy_add`,
  `proxy_search`.

- **Fix:** `agentmemory/runtime/http_client.py` now requires callers to pass
  `infer` to `proxy_add` and `rerank` to `proxy_search` explicitly. This turns
  future omissions into immediate `TypeError`s instead of silently reviving old
  proxy-layer defaults. Regression tests cover the explicit-failure path, and
  the current tree has no remaining implicit call sites.

---

## 18. HTTP body size is not capped

- **Status:** closed
- **Severity:** bug (local DoS)
- **Why:** `AgentMemoryHandler._read_json` reads
  `int(self.headers.get("Content-Length", "0"))` bytes with no upper
  bound. A malformed or malicious local request can request tens of GB
  allocation and OOM the API process. This is on top of BACKLOG #2
  (rate limiting) — the cap is per-request, the rate limit is per-minute;
  both are needed.

- **Where:** `agentmemory/api.py::AgentMemoryHandler._read_json`
  (≈ L89–92).

- **Fix:** the API now caps request bodies at `16 MiB` by default
  (overridable via `AGENTMEMORY_MAX_BODY_BYTES`). Declared oversized bodies are
  rejected before reading, and bodies without `Content-Length` are read with a
  strict ceiling. HTTP endpoints return `413 Payload Too Large`, and the MCP
  endpoint returns a JSON-RPC error with the same HTTP status. Regression tests
  cover declared and undeclared oversized bodies.

---

## 19. Client-registration paths hardcode Windows `AppData/Roaming`

- **Status:** open
- **Severity:** bug (cross-platform correctness)
- **Why:** `agentmemory/clients.py` defines `CLAUDE_DESKTOP_CONFIG`,
  `VSCODE_MCP`, `ROO_MCP`, `KILO_MCP`, `CLINE_*_MCP` as
  `Path.home() / "AppData" / "Roaming" / ...`. On macOS or Linux this
  produces paths like `~/AppData/Roaming/Code/...` — neither a real config
  location nor an empty miss. `connect-clients` and `doctor-clients` will
  either skip them as non-existent or, worse, create garbage directories.

- **Where:** `agentmemory/clients.py` — module-level path constants
  (L22–27).

- **Fix:** `agentmemory/clients.py` now resolves client config paths through
  platform-aware helpers instead of hardcoded Windows `AppData/Roaming`
  constants. Windows uses `%APPDATA%` (fallback `~/AppData/Roaming`), macOS
  uses `~/Library/Application Support`, and Linux uses `$XDG_CONFIG_HOME`
  (fallback `~/.config`). `connect-clients`, `status-clients`, and
  `doctor-clients` now read those helpers at call time, so non-Windows runs no
  longer inspect or create fake `~/AppData/Roaming/...` trees.
  `tests/test_agentmemory_clients.py` covers Windows, macOS, Linux, and the
  Linux lowercase `claude` fallback for existing setups.

---

## 20. `ensure_api_running` has a cold-start race

- **Status:** closed
- **Severity:** bug
- **Why:** Two non-owner processes that both call `ensure_api_running`
  at the same time each see `api_is_healthy() == False`, each
  `Popen` a fresh API, and race on the PID file. The later write wins;
  the loser becomes an orphan still bound to the port. The owner process
  that later calls `stop-api` kills the recorded PID, leaving the orphan
  holding the port until OS cleanup.

- **Where:** `agentmemory/runtime/http_client.py::ensure_api_running`
  (L78–102), `agentmemory/cli.py::start_api_process` (L484–514).

- **Fix:** `agentmemory/runtime/http_client.py::ensure_api_running` now holds
  a cross-process lock file across the entire cold-start critical section:
  re-check health, launch the API, clear runtime caches, and wait for readiness.
  Competing callers now serialize instead of double-starting the owner API.
  Regression coverage includes a real multiprocessing test that starts two
  concurrent callers against the same lock file and verifies only one launcher
  path runs.

---

## 21. `stop-api` on Windows force-kills without graceful shutdown

- **Status:** closed
- **Severity:** bug
- **Why:** `cli.py::stop_api_process` uses `taskkill /F` on Windows,
  which skips the `SIGTERM`-style handler that would otherwise flush
  the TTL sweeper and remove the PID/state files. The PID/state files
  are then removed by `stop-api` itself, but during the force-kill
  window another process can observe a dead PID as live.

- **Where:** `agentmemory/cli.py::stop_api_process` (L545–551).

- **Fix:** `agentmemory/cli.py::stop_api_process` now uses a two-phase
  shutdown path. On Windows it first calls `taskkill /PID <pid>` without `/F`,
  waits for the process to exit, and escalates to `/F` only if the grace period
  expires. On POSIX it now mirrors the same contract with `SIGTERM` followed by
  a bounded wait and `SIGKILL` fallback. Regression tests cover the POSIX path,
  Windows graceful success, and Windows forced escalation.

---

## 22. Error payload shape diverges between HTTP / MCP / CLI

- **Status:** closed
- **Severity:** hygiene (client-integration friction)
- **Why:** HTTP returns `{"error": "...", "error_type": "...",
  "message": "..."}` (two of the three keys duplicate each other).
  MCP returns `{"error_type": "...", "message": "..."}` embedded as
  JSON in `content[0].text`, with `isError: true`. CLI prints
  `str(exc)` to stderr with no structure. A client writing a unified
  wrapper around AgentMemory has to branch per surface to extract the
  same information.

- **Where:** `agentmemory/api.py::_send_error_payload` (L94–98),
  `agentmemory/mcp.py::error_result` (L52), `agentmemory/ops_cli.py`
  error path (L102–103).

- **Fix:** `agentmemory/providers/base.py` now exposes the shared
  `provider_error_payload()` helper, and transport surfaces route through it.
  CLI stderr now emits the same structured JSON `{error_type, message}` shape
  used by MCP and HTTP. HTTP retains `"error"` as a compatibility alias while
  the canonical structured keys remain `error_type` and `message`.

---

## 23. `memory_add` metric counts dedup hits as inserts

- **Status:** open
- **Severity:** hygiene (observability correctness)
- **Why:** `OperationSpec.__post_init__` wraps `execute` with
  `metrics_registry.timed(name)`. `_execute_add` returns a pre-existing
  record when `_maybe_dedup_existing` fires, without inserting. Both
  paths increment `memory_add.ok`, so the counter is the sum of real
  inserts plus dedup reads. There is no separate counter for dedup
  hits, and the silent `except Exception: return None` inside
  `_maybe_dedup_existing` hides provider errors during the dedup
  probe.

- **Where:** `agentmemory/runtime/operations.py` — `_maybe_dedup_existing`
  (L107–123) and `_execute_add` (L137–140).

- **Fix outline:** introduce counters
  `memory_add.dedup_hit`, `memory_add.inserted`,
  `memory_add.dedup_probe_failed`. Keep `memory_add.ok` as a sum for
  back-compat. Log a `warn` line with `error_type` when the dedup
  probe raises, so silent failure becomes discoverable.

---

## 24. `should_proxy_to_api` reads cached runtime policy

- **Status:** closed
- **Severity:** bug (latent)
- **Why:** `active_provider_runtime_policy` in
  `agentmemory/runtime/config.py` is `@lru_cache`'d. If the owner API
  process reloads a new config (provider switched from `mem0` to
  `localjson`, or transport mode flipped), other long-lived processes
  continue to route by the old decision. Today this manifests only
  during manual reconfiguration, which is uncommon — but future
  features like `POST /admin/reload` would expose the divergence
  immediately.

- **Where:** `agentmemory/runtime/http_client.py::should_proxy_to_api`
  (L26–33) and `agentmemory/runtime/config.py::active_provider_*`
  cached accessors.

- **Fix:** `agentmemory/runtime/config.py` now wraps its cached runtime config
  and provider accessors with automatic invalidation keyed to the config file
  marker (`path`, existence, `mtime_ns`, and size). Long-lived processes now
  observe provider/runtime-policy changes after on-disk config updates without
  requiring manual `clear_caches()`. Regression tests cover both runtime policy
  and capability updates after an external config-file rewrite.

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
