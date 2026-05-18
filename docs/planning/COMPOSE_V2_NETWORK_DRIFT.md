# Compose V2 External-Network Drift

This document captures the upstream-facing defect behind AgentMemory backlog
item `#3`.

AgentMemory already ships a local guard:

- [deploy/redeploy.sh](../deploy/redeploy.sh)

The purpose of this document is to make the issue reproducible, explain why the
guard exists, and provide an issue-ready report for `docker/compose`.

## Short Version

Observed on the production host:

- `docker compose up -d --build --force-recreate`
- service declares both an internal network and an external network
- after recreate, the container can come back missing the external network
- Traefik or another peer on that external network can no longer reach it

This has been observed with `netbird_netbird` on the host used for AgentMemory.

AgentMemory mitigates it by reattaching the container idempotently after
recreate:

```bash
docker network connect netbird_netbird agentmemory 2>&1 \
  | grep -v "already exists" \
  || true
```

## Why This Matters

This is not a cosmetic deploy quirk.

If the external reverse-proxy/shared network disappears, the service can look
healthy from inside its own container while being unreachable from the actual
ingress path.

That mismatch is exactly why AgentMemory keeps the self-heal in
`deploy/redeploy.sh`.

## Minimal Reproducer

Use the helper script:

```bash
deploy/repro-compose-network-drift.sh
```

The script:

- creates a temporary external bridge network
- creates a temporary compose project with:
  - one external network
  - one internal project network
- runs `docker compose up -d --force-recreate` twice
- inspects the resulting network attachments
- exits non-zero if the external network is missing after recreate

The repro is intentionally self-cleaning and uses temporary names.

## Manual Reproducer Shape

If you want the minimal logic without the helper script, the setup is:

1. Create an external network once:

```bash
docker network create am-repro-external
```

2. Use a compose file like:

```yaml
services:
  app:
    image: nginx:alpine
    networks:
      - external_net
      - internal

networks:
  external_net:
    external: true
    name: am-repro-external
  internal:
```

3. Run twice:

```bash
docker compose up -d --force-recreate
docker compose up -d --force-recreate
docker inspect app --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'
```

Observed bad behavior:

- the internal/project network remains
- the external network is sometimes missing after recreate

Expected behavior:

- both declared networks remain attached after each recreate

## Issue Draft For Upstream

Title:

`[BUG] docker compose up --force-recreate can drop declared external network attachment`

Body:

```text
### Description

We have observed `docker compose up -d --build --force-recreate` bringing a
container back without one of its declared external networks.

The compose service declares:
- one external bridge network
- one internal/project network

After recreate, the service sometimes comes back attached only to the internal
network. The external network is missing until we manually run:

docker network connect <external-network> <container>

This was observed in production on a service behind Traefik, where the service
looked healthy from inside the container but was unreachable from the reverse
proxy because the shared external network attachment had disappeared.

### Expected behavior

A recreated container should remain attached to every declared network,
including declared external networks.

### Actual behavior

After recreate, the container can come back missing the external network
attachment even though the compose file still declares it.

### Minimal reproducer

- create one external bridge network once
- create a compose service attached to:
  - the external network
  - one internal project network
- run `docker compose up -d --force-recreate` twice
- inspect `.NetworkSettings.Networks`

### Workaround

We currently self-heal with:

docker network connect <external-network> <container> 2>&1 | grep -v "already exists" || true

### Impact

This creates a mismatch where the container may still pass its own local
healthcheck while becoming unreachable to other services that depend on the
external network attachment.
```

## Repo Policy

Inside this repository, the issue is considered operationally closed because:

- the guarded redeploy path exists
- the guard is documented
- the reproducer and issue draft now live in-repo

The upstream root cause is still outside AgentMemory itself.
