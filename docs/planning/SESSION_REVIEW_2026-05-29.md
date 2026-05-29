# Session Review — 2026-05-29

Snapshot of the system's real state after a multi-day work arc that landed:
DCR (RFC 7591), refresh tokens with rotation (RFC 6749), persistent token
store, file-mode hardening, the four live-review bug fixes, off-host backup,
hardened `redeploy.sh` with a network-attachment gate, applied the
network-gate pattern to the TRC stack, and aligned CI triggers to `master`.

This document is a **honest assessment** — what works, what's brewing,
what's worth fixing, what to leave alone. Use it as the source of context
when triaging individual `BACKLOG.md` items below.

---

## 1. What is working without caveats

| Layer | State |
|---|---|
| Code | 460 tests passing across the full suite, CI green on master, all four review bugs closed with regression tests, all recent commits deployed to production. |
| OAuth 2.1 | DCR + refresh tokens + rotation work end-to-end through the Claude.ai connector. Verified live with a real `memory_add(infer=true)` round-trip on 2026-05-29. |
| Persistence | Tokens (`oauth_tokens.json`), registered clients (`oauth_clients.json`), `scope_registry.sqlite3`, qdrant — all in the `deploy_agentmemory_data` volume, captured by the daily backup tarball. |
| Backup chain | Server cron `0 4 * * *` -> tarball in `/var/backups/agentmemory/` (14-day rolling) -> Windows Task Scheduler at 12:30 local pulls to `O:\backups\agentmemory\` (30-day rolling). Two independent copies on independent disks. |
| Deploy | `redeploy.sh` reconciles BOTH expected networks idempotently and refuses to declare ready unless both are attached. Negative-test verified — exits 1 with `FATAL` if any expected network is missing. |
| Docs | `/root/docs/agentmemory/OVERVIEW.md` and `RUNBOOK.md` reflect current state (off-host backup section, docker-restart warning, OAuth model). `INDEX.md` links them. `README.md` and `CHANGELOG.md` in repo are current. |
| Memory state | 47 records live in production (44 in one legal-case pool tagged with `user_id=topazd2 + agent_id=family_court_child_residence_alimony_case`, 3 in an ops-notes pool tagged `user_id=andrewmoryakov`). All retrievable through MCP, persistence confirmed across restarts. |

---

## 2. Real problems present today

### P1 — Legal-case memory pool (44 records) is structurally fragile

Observed when inspecting actual records. Pattern of use:

- 44 records in a single `(user_id=topazd2, agent_id=family_court_child_residence_alimony_case)` scope.
- Text contains hand-rolled structural markup like
  `[BANK STATEMENT ANALYSIS / april_2026 / child_residence_alimony_arseniy]`
  or `[NEW EVIDENCE / extended_period_aggregate_figures / ...]`.
- Some records carry rich metadata (`case`, `chunk`, `source`, `verified_until`,
  `evidence_status`), others have `metadata: {}` empty — inconsistent.
- Cross-references between records are strings (e.g. `related_chunk:
  "16_2026-05-11_to_2026-05-15"`) — not foreign keys.
- Aggregate records contain time-bounded totals (e.g. "ИТОГО 297 580 руб.
  за период до 27.05.2026") with no signal of when they become stale.
- "Document 1 v3" appears in text — implying v1/v2 exist somewhere — but
  there is no version awareness at the memory layer.

Concrete consequences already in play:

1. Aggregate records will be returned by semantic search as authoritative
   long after they go stale, because nothing marks them stale.
2. Cross-references break silently if the target is deleted or renamed.
3. Searches for "all monthly bank reports" rely on text similarity to the
   `[BANK STATEMENT ANALYSIS]` prefix, not on a structural filter, because
   metadata is inconsistent.
4. The reranker picks top-K from semantically-overlapping records (multiple
   monthly reports + an aggregate + thematic notes — all topically similar)
   and the caller has no way to know what got cut.

This pattern is using memory as a **document store**, which is not what mem0
is designed for. It works at 44 records; it will degrade as the pool grows.

### P2 — `telepilothub.duckdns.org` adjacent outage

Discovered during the TRC redeploy work on 2026-05-29:
`https://telepilothub.duckdns.org/` returns HTTP 000 from both the VPS
itself and external clients. The container `telegramremotecontrol-hub-1`
is healthy and reachable directly on `netbird_netbird` by IP (HTTP 200 on
`/`). The outage is in the Traefik routing chain or DuckDNS DNS, not in
the app. Saved in memory as `status: known_open`.

This is not our system, but it is adjacent infrastructure on the same host
and would be discovered by anyone reviewing the deploy.

### P3 — TRC `redeploy.sh` is uncommitted

`/root/telegramremotecontrol/redeploy.sh` was installed and tested on the
server but is untracked in the TRC git repository (which has separate
ownership: `AndrewMoryakov/TelegramRemoteControl`). Any `git reset --hard`
on that repo will delete it. The script itself self-documents the
network-gate pattern and references the host-canonical
`/root/scripts/compose-deploy-guard.sh`.

### P4 — No monitoring / no failure alerts

The earliest you would learn that a backup is silently failing is when
you tried to restore. We have:

- a server-side backup log (`/var/log/agentmemory-backup.log`)
- a local pull log (`O:\backups\agentmemory-pull.log`)
- CI status on GitHub
- container healthcheck (returns 200 even when downstream is broken — by
  design, see `docker-compose.yml`)

We do not have:

- alert if `0 4 * * *` cron fails or doesn't run
- alert if Task Scheduler `AgentMemory-Pull-Backups` last result != 0
- alert if `https://agentmemorytool.duckdns.org/health` starts returning
  non-200
- alert if the data volume fills up

This is the highest-leverage operational gap. A single healthchecks.io
URL pinged at the end of each successful backup, with a 26-hour SLA on
the dead-man side, would close most of the silent-failure surface.

---

## 3. Problems brewing — 1 to 6 months out

| # | Issue | Trigger | Mitigation cost |
|---|---|---|---|
| F1 | Search degradation as the legal pool grows past ~100-200 records. The reranker has finite ability to discriminate between topically-overlapping records. | Continued single-pool growth at the current rate. | Medium — needs workflow shift or pool curation. |
| F2 | `infer=true` fan-out multiplies the working set. If turned on accidentally where verbatim was wanted, a 44-record pool becomes 130-440 atomic fragments. | Configuration mistake by a client. | Low — could add safety rails (warn if fan-out > N). |
| F3 | Multi-tenant isolation is filter-based, not storage-based. All records live in one qdrant collection. A client bug that forgets to set `user_id` or accepts it from untrusted input would leak records across users. | Adding a second real user, or any client bug around user_id. | Medium — needs an API gate that derives `user_id` from auth context, not from payload. |
| F4 | OAuth lifecycle: 7-day access, 30-day refresh. A user who does not use the connector for 30+ days has to re-authorize. | Long absence. | Low — accept it, or document the renewal step. |
| F5 | `mem0` single-owner-process model: only one process can talk to qdrant directly. Others must proxy through the API server. Limits concurrent-writer throughput. | High write rate or a desire to scale horizontally. | High — different storage backend or different provider. |
| F6 | Stale GitHub branch `claude/explore-project-UFGBJ` — 13 commits ahead, 48 behind master. Real work by a previous Claude agent, never merged. | Whenever someone notices and wonders. | Low — review diff and decide. |

---

## 4. What to do — by priority

### Today (1-3 hours, real return)

1. **Healthchecks.io ping at the end of `backup-agentmemory.sh` and
   `pull-agentmemory-backups.ps1`** — closes most of the silent-failure
   surface (P4). One free account, one URL per cron, dead-man alerts via
   email if a ping is missing. ~30 min.
2. **Cron healthcheck on `agentmemorytool.duckdns.org/health`** —
   `*/10 * * * * curl -fsS .../health || curl -fsS https://hc-ping.com/.../fail`
   on the server itself. ~10 min.
3. **Document the metadata convention for the legal-case agent** in the
   agent's system prompt: `kind` (evidence | analysis | aggregate |
   context | draft), `event_date` (ISO), `stale_after` (ISO for aggregates).
   Pure prompt change, no code. Closes 80% of the P1 surface for new
   records. ~15 min.
4. **Commit TRC `redeploy.sh` to its repo** — requires user decision /
   PR through the TRC project. Just a `git add && git commit` once
   the user approves.

### Soon (1-2 weeks, preventive)

5. **Triage the telepilothub outage (P2)** — likely Traefik label /
   route refresh or DuckDNS A-record. ~1 hour.
6. **Curate the legal pool once** — mark superseded versions with
   `metadata.archived: true`, set `stale_after` on existing aggregates.
   Can be done by the legal-case agent itself, walking the pool. ~30 min
   of agent time.
7. **Baseline measurement for F1** — run 5 thematic queries against the
   legal pool, record top-10 plus a subjective "did it find what
   mattered" score. Repeat in a month — quantifies whether F1 is
   actually getting worse or staying acceptable.

### Later (3-6 months or when something signals)

8. **F1: workflow shift if search has visibly degraded** — re-curate
   the legal pool into living summary records (one per topic, updated
   in place) and archive the raw chunks elsewhere (file system, dedicated
   doc store). Memory becomes "current state", not "full history".
9. **F3: real multi-tenant isolation when a second user appears** —
   either separate deployments per tenant, or a hard API gate that
   refuses payloads where `user_id` differs from the auth-derived
   identity.
10. **F5: replace mem0 if concurrent writes start mattering** — different
    storage backend or a different provider implementation that supports
    multi-writer natively.

### Explicitly do not do

- Implement "links between records" inside memory — that is a graph DB
  feature, not a memory feature. If links are needed, the data does not
  belong in mem0.
- Implement "versions of records" — same reasoning, that is what git or
  a dedicated doc store is for.
- Add features without a real use case — refresh-token revocation, audit
  log, replication, federation. None of these are hurting now.

---

## 5. Bottom line

The system is ready for productive use by one person. All critical paths
work, two independent backup copies exist, documentation reflects reality,
memory persists across restarts. This is production-grade for a single
user; treat that as the success line.

The biggest risk for the next month is not a code bug — it is **silent
operational failure** (P4) and **slow memory degradation** (P1/F1)
without an alert telling anyone. Both are addressable cheaply and
locally without architectural change.

Almost everything in section 3 is speculative until evidence appears.
Resist building for those scenarios in advance.
