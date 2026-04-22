# Deploy AgentMemory behind Traefik

This guide deploys AgentMemory as a remote MCP + HTTP service on a server
that already runs Traefik (for example, the `andrewm.ru` ingress host).

The public URL after setup is:

```
https://andrewm.ru/agentmemory/
```

with these paths:

- `GET  /agentmemory/health` — liveness probe (open)
- `POST /agentmemory/mcp` — MCP over HTTP (bearer-token protected)
- `POST /agentmemory/add|search|search/page|update` — legacy HTTP API (bearer-token protected)
- `GET  /agentmemory/memories`, `/agentmemory/admin/...` — admin/read APIs (bearer-token protected)
- `GET  /agentmemory/memories/page` — cursor-page memory list API (bearer-token protected)

The browser UI is disabled on remote deployments via `AGENTMEMORY_DISABLE_UI=1`.

## 1. Prepare the server

Pick a directory, for example `/opt/agentmemory`, and clone the repo there:

```bash
mkdir -p /opt/agentmemory
cd /opt/agentmemory
git clone <your-repo-url> .
```

## 2. Create `.env`

Generate a strong token and write the `.env`:

```bash
cp .env.example .env
TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
sed -i "s|^AGENTMEMORY_API_TOKEN=.*|AGENTMEMORY_API_TOKEN=$TOKEN|" .env
sed -i "s|^AGENTMEMORY_DISABLE_UI=.*|AGENTMEMORY_DISABLE_UI=1|" .env
# optional, only needed for the mem0 provider
# sed -i "s|^OPENROUTER_API_KEY=.*|OPENROUTER_API_KEY=<your-key>|" .env
echo "API token: $TOKEN"
```

Save the printed token — MCP/HTTP clients need it.

## 3. Seed the xray tunnel (only if the host VPS is region-blocked)

Some cloud providers block the IPs used by OpenRouter's embedding backends.
Symptom: `/health` is green but `memory_add` returns
`ProviderUnavailableError: 'NoneType' object is not subscriptable`, because the
OpenAI SDK receives `{"error": {"message": "No successful provider responses."}}`.

The fix used here is a VLESS+Reality tunnel on a cooperating secondary host,
fronted by an `xray` sidecar that exposes SOCKS5 (1080) + HTTP CONNECT (1081)
on the `agentmemory-proxy` internal network. The agentmemory container
uses `HTTP_PROXY`/`HTTPS_PROXY` pointing at it.

Copy the template and fill in the tunnel credentials (the file is gitignored):

```bash
cp deploy/xray-proxy.example.json deploy/xray-proxy.json
# Edit with the VLESS user uuid, reality publicKey/shortId, and remote host
```

If your host VPS can reach OpenRouter embeddings directly, this step is optional
— you can still use `localjson` without a tunnel, or skip mounting the proxy.

## 4. Start the container

```bash
# The recommended path — one command, runs both guards and verifies:
deploy/redeploy.sh
```

`deploy/redeploy.sh` wraps `docker compose up -d --build --force-recreate`,
forcibly re-attaches the container to `netbird_netbird` (idempotent), and
waits for `https://andrewm.ru/agentmemory/health` to return `200`. Exits
non-zero if the backend hasn't come back within ~60 seconds, so CI / cron
can catch partial deploys.

Manual equivalent if the script isn't convenient:

```bash
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build --force-recreate
docker network connect netbird_netbird agentmemory 2>&1 \
  | grep -v "already exists" || true
docker logs agentmemory --tail 30
```

Compose v2 has been observed silently dropping non-primary network
attachments on plain `up -d` (see `/opt/telegramchatanalyzer/POSTMORTEM_NETWORK_DETACH.md`).
`--force-recreate` doesn't always prevent it either; the manual
`docker network connect` is the guarantee.

## 5. Plug into Traefik

Copy the file-provider route into Traefik's dynamic config directory:

```bash
cp deploy/traefik-agentmemory.yml /root/netbird/traefik-conf/agentmemory.yml
```

Traefik watches this directory (`--providers.file.watch=true`), so no
restart is required. Verify from the host:

```bash
curl -s https://andrewm.ru/agentmemory/health
# -> {"ok": true}
```

## 5. Smoke-test the MCP endpoint

```bash
TOKEN="..."  # from step 2

curl -sS https://andrewm.ru/agentmemory/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}'

curl -sS https://andrewm.ru/agentmemory/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

The first call returns `serverInfo`; the second lists the memory tools.

Large memory walks should use `memory_list_page` or `memory_search_page` and
follow `next_cursor` until it is `null`. Provider-neutral export automatically
uses cursor pages for providers that declare `supports_pagination = true`; for
legacy non-paginated providers it still fails closed at the fixed safety guard
instead of silently truncating data.

## 6. Connect a remote MCP client

### Claude (Desktop or claude.ai Custom Connectors)

Add a Custom Connector with:

- **Type:** Remote MCP / HTTP
- **URL:** `https://andrewm.ru/agentmemory/mcp`
- **Header:** `Authorization: Bearer <token>`

### ChatGPT (Custom Connectors — MCP over HTTP)

Add a connector with:

- **Server URL:** `https://andrewm.ru/agentmemory/mcp`
- **Authentication:** Custom header `Authorization: Bearer <token>`

ChatGPT requires HTTPS; the Let's Encrypt cert on `andrewm.ru` covers it.

## Observability

Two endpoints expose runtime metrics (bearer-gated like everything else):

```
GET /agentmemory/metrics                 # Prometheus text format
GET /agentmemory/admin/stats/operations  # JSON summary
```

The Prometheus endpoint emits:

- `agentmemory_operation_ok_total{operation}` — per-tool success counter
- `agentmemory_operation_error_total{operation, error_type}` — per-tool error counter by class
- `agentmemory_operation_latency_seconds{operation}` — histogram with p50/p95/p99 derivable
- `agentmemory_llm_tokens_total{model, kind}` — prompt/completion tokens per model
- `agentmemory_llm_cost_usd{model}` — estimated spend per model, pricing in `agentmemory/runtime/metrics.py`

Costs are approximate — pricing in the lookup table reflects OpenRouter's
rates at the time the model was added. Unknown models still count tokens
but contribute `0` to cost totals.

Hook a scraper later if needed; there is no Prometheus server on the host.

## Memory lifecycle

**TTL.** `memory_add` accepts either `metadata.ttl_seconds` (positive number)
or `metadata.expires_at` (ISO-8601 UTC). The runtime normalizes both to a
stored `expires_at`. Expired records are filtered from `memory_list`/
`memory_search` on read, and `memory_get` on an expired id raises
`MemoryNotFoundError` — matching the hard-delete contract.

A background sweeper in the API process hard-deletes expired records every
10 minutes by default. Override with `AGENTMEMORY_TTL_SWEEP_MINUTES` (env,
float minutes; `0` disables the sweeper so reads alone enforce TTL).

**Dedup.** Pass `dedup: true` to `memory_add` (requires scope +
semantic-search provider) to run a similarity search before the insert. If
any existing record in the same scope scores ≥0.92, the tool returns that
record with `dedup_hit: true` and `dedup_score` instead of creating a
duplicate. `infer=true` rewrites still get de-duplicated against the
rewritten text.

**Reconcile.** Run `memory_reconcile` or `agentmemory reconcile-memories` with
`user_id`, `agent_id`, or `run_id` to perform a read-only memory hygiene check.
The first pass uses conservative deterministic heuristics to surface likely
conflicting claim pairs; it never edits, deletes, or supersedes records.

## Network topology

```
                     ┌───────────────────────────────────────────┐
                     │            andrewm.ru:443 (TLS)           │
                     └──────────────────┬────────────────────────┘
                                        │
                                ┌───────▼─────────┐
                                │     traefik     │  netbird_netbird
                                └───────┬─────────┘
                                        │ http://agentmemory:8765
                                        │
┌─────────────┐                ┌────────▼────────┐       ┌──────────────────┐
│ deploy_     │    HTTP CONNECT│   agentmemory   │       │ agentmemory-proxy│
│ internal    │◄───────────────┤                 │       │  (xray sidecar)  │
│             │    :1081       │  (mem0 + API)   │       │                  │
└─────────────┘                └────────┬────────┘       └──────────────────┘
                                        │
                                        │ (two network memberships)
                                        ▼
                                 netbird_netbird
```

**Invariants that matter** (from the post-mortem that drove these guards):

1. `agentmemory` MUST be on both `netbird_netbird` (so Traefik sees it) and
   `deploy_internal` (so it can reach `agentmemory-proxy`). Losing the
   Traefik membership yields 502; losing internal membership breaks
   embeddings with a misleading `NoneType` error.
2. `agentmemory-proxy` stays on `deploy_internal` only. It has zero public
   surface; no host port is published.
3. `docker compose up -d` without `--force-recreate` can drift the first
   invariant. Always recreate.
4. Traefik's file-provider route has a loadBalancer healthCheck on
   `/health`, so misattachments surface as 503 (self-describing), not 502.

## Health-endpoint exposure policy

`memory_health` (MCP tool) and `GET /health` (HTTP, authenticated) return a
verbose payload: container paths, listener PID, provider name, model names,
embedding dimensions, and the whole `provider_contract` block. Today this
is acceptable because:

- Every caller authenticates with the same bearer token or OAuth client.
- There is one real user (the owner).
- No untrusted tenant shares the runtime.

If access is ever opened up — an AI-tool marketplace, a shared team, an
LLM application using the MCP on behalf of unknown end-users — **split
the health surface before flipping the switch**. Two reasonable shapes:

1. Public `memory_health` returns `{ok, contract_version, scope_kinds}`
   only; all path/PID/model fields move to a new `memory_health_debug`
   tool gated by an additional scope or header.
2. Keep one tool but strip verbose fields from the response whenever the
   bearer token is missing or belongs to a non-ops scope.

`GET /health` (unauthenticated liveness) already returns `{"ok": true}`
only; no change needed there.

**Decision:** no split today. This section is a reminder for the future
change — if you see this doc before opening access, do the split first.

## Backup and restore

Memory lives in the `deploy_agentmemory_data` Docker volume (Qdrant +
SQLite + localjson JSON file). Config + secrets live in `.env`,
`deploy/agentmemory.config.json`, and `deploy/xray-proxy.json`. A helper
script bundles all of them into one dated tarball:

```bash
# on the server
/opt/agentmemory/deploy/backup-agentmemory.sh
# default output: /var/backups/agentmemory/agentmemory-<UTC-timestamp>.tar.gz
```

Environment overrides: `BACKUP_DIR`, `VOLUME_NAME`, `PROJECT_DIR`,
`BACKUP_RETAIN` (keep N most recent, default 14).

**Restore outline:**

```bash
cd /opt/agentmemory
docker compose -f deploy/docker-compose.yml --env-file .env down
# Expand the bundle into /var/backups/agentmemory/ and pull out the inner
# archives. The data archive restores into the volume; the config archive
# restores into the project dir.
tar -xzf agentmemory-<ts>.tar.gz -C /tmp/restore/
docker run --rm -v deploy_agentmemory_data:/data \
  -v /tmp/restore:/backup alpine sh -c \
  'cd / && tar -xzf /backup/agentmemory-data-<ts>.tar.gz'
tar -xzf /tmp/restore/agentmemory-config-<ts>.tar.gz -C /opt/agentmemory
docker compose -f deploy/docker-compose.yml --env-file .env up -d --force-recreate
```

The tarball contains secrets (API token, OpenRouter key, OAuth client
secret, xray tunnel credentials). Store it on a private filesystem; if
it will leave the host, encrypt at rest (age, gpg, rclone crypt).

A simple schedule (daily at 04:00 UTC, keep 14 days):

```cron
0 4 * * * /opt/agentmemory/deploy/backup-agentmemory.sh >> /var/log/agentmemory-backup.log 2>&1
```

## Updating the deployment

```bash
cd /opt/agentmemory
git pull
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build --force-recreate
# Self-heal guard (idempotent):
docker network connect netbird_netbird agentmemory 2>&1 | grep -v "already exists" || true

# Post-deploy smoke test
TOKEN="$(grep ^AGENTMEMORY_API_TOKEN= .env | cut -d= -f2)"
curl -fsS https://andrewm.ru/agentmemory/health >/dev/null && echo "health ok"
curl -fsS -X POST https://andrewm.ru/agentmemory/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('tools:',len(d['result']['tools']))"
```

## Rotating the token

```bash
NEW="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
sed -i "s|^AGENTMEMORY_API_TOKEN=.*|AGENTMEMORY_API_TOKEN=$NEW|" .env
docker compose -f deploy/docker-compose.yml --env-file .env up -d
```

Update the connector config in each client with the new token.
