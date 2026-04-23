#!/usr/bin/env bash
# Redeploy AgentMemory with the guards the network-drift postmortem says we
# need: --force-recreate plus an idempotent re-attach to netbird_netbird.
# Run this instead of raw docker compose up whenever deploying or updating on
# the production host. Context and reproducer live in
# docs/COMPOSE_V2_NETWORK_DRIFT.md.

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/agentmemory}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-.env}"
TRAEFIK_NETWORK="${TRAEFIK_NETWORK:-netbird_netbird}"
APP_CONTAINER="${APP_CONTAINER:-agentmemory}"
PUBLIC_HEALTH_URL="${PUBLIC_HEALTH_URL:-https://andrewm.ru/agentmemory/health}"

cd "${PROJECT_DIR}"

echo "== docker compose up -d --build --force-recreate =="
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d --build --force-recreate

echo "== Self-heal: ensure ${APP_CONTAINER} is on ${TRAEFIK_NETWORK} =="
# Compose v2 has been observed silently dropping declared external-network
# attachments on recreate. docker network connect is idempotent — if already
# attached, docker returns an "already exists" error which we suppress.
docker network connect "${TRAEFIK_NETWORK}" "${APP_CONTAINER}" 2>&1 \
  | grep -v "already exists" \
  || true

echo "== Network memberships =="
docker inspect "${APP_CONTAINER}" \
  --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'

echo "== Waiting for Traefik backend to go healthy =="
for i in $(seq 1 20); do
  status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 4 "${PUBLIC_HEALTH_URL}" || echo "000")"
  echo "  attempt ${i}: HTTP ${status}"
  if [ "${status}" = "200" ]; then
    echo "== Ready =="
    exit 0
  fi
  sleep 3
done

echo "WARNING: backend did not report 200 within the wait window." >&2
echo "  Last status: ${status}" >&2
echo "  docker ps:" >&2
docker ps --filter "name=agentmemory" --format "  {{.Names}}\t{{.Status}}" >&2
exit 1
