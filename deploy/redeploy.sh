#!/usr/bin/env bash
# Redeploy AgentMemory with the guards the network-drift postmortem says we
# need: --force-recreate plus an idempotent re-attach to every network the
# container is supposed to be on. Run this instead of raw docker compose up
# (and never use `docker restart` on this stack — see RUNBOOK).
#
# Why both networks matter:
#   netbird_netbird  — Traefik ingress reaches the container here.
#   deploy_internal  — agentmemory talks to agentmemory-proxy (the xray
#                      sidecar) here for OpenRouter outbound. If this one
#                      drops, /health stays 200 but every embedding/LLM
#                      call fails because the proxy host can't be resolved.
#
# Compose v2 on this host has been observed silently dropping EITHER network
# on recreate, and `docker restart` is known to drop deploy_internal at least.
# We reconnect both idempotently after the recreate and refuse to claim
# "ready" until both are actually attached.
#
# Context: deploy/COMPOSE_V2_NETWORK_DRIFT.md
#          /opt/telegramchatanalyzer/POSTMORTEM_NETWORK_DETACH.md
#          /root/docs/agentmemory/RUNBOOK.md

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/agentmemory}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-.env}"
APP_CONTAINER="${APP_CONTAINER:-agentmemory}"
# Space-separated list. Override via env if the topology changes.
EXPECTED_NETWORKS="${EXPECTED_NETWORKS:-netbird_netbird deploy_internal}"
PUBLIC_HEALTH_URL="${PUBLIC_HEALTH_URL:-https://agentmemorytool.duckdns.org/health}"

cd "${PROJECT_DIR}"

echo "== docker compose up -d --build --force-recreate =="
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d --build --force-recreate

echo "== Self-heal: ensure ${APP_CONTAINER} is on every expected network =="
# docker network connect is idempotent — if already attached, docker returns
# an "already exists" error which we suppress.
for network in ${EXPECTED_NETWORKS}; do
  echo "  reconciling ${network}"
  docker network connect "${network}" "${APP_CONTAINER}" 2>&1 \
    | grep -v "already exists" \
    || true
done

echo "== Network memberships =="
actual_networks="$(docker inspect "${APP_CONTAINER}" \
  --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}')"
echo "  ${actual_networks}"

# Fail loud if a required network is still missing — the silent-drift
# scenario the comment block above is about. Don't proceed to the health
# wait because /health does not exercise the proxy chain and would lie.
for network in ${EXPECTED_NETWORKS}; do
  case " ${actual_networks} " in
    *" ${network} "*) ;;
    *)
      echo "FATAL: ${APP_CONTAINER} is not attached to ${network}" >&2
      echo "  Attached: ${actual_networks}" >&2
      exit 1
      ;;
  esac
done

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
