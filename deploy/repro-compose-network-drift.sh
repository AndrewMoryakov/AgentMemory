#!/usr/bin/env bash
# Minimal self-cleaning reproducer for the compose-v2 external-network drift
# documented in docs/COMPOSE_V2_NETWORK_DRIFT.md.

set -euo pipefail

TMP_ROOT="$(mktemp -d)"
PROJECT_NAME="amrepro$$"
EXTERNAL_NETWORK="${EXTERNAL_NETWORK:-am-repro-external-$PROJECT_NAME}"
CONTAINER_NAME="${CONTAINER_NAME:-am-repro-app-$PROJECT_NAME}"
COMPOSE_FILE="$TMP_ROOT/docker-compose.yml"

cleanup() {
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
  docker network rm "$EXTERNAL_NETWORK" >/dev/null 2>&1 || true
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

cat >"$COMPOSE_FILE" <<EOF
services:
  app:
    image: nginx:alpine
    container_name: $CONTAINER_NAME
    networks:
      - external_net
      - internal

networks:
  external_net:
    external: true
    name: $EXTERNAL_NETWORK
  internal:
EOF

echo "== create external network =="
docker network create "$EXTERNAL_NETWORK" >/dev/null

echo "== first recreate =="
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d --force-recreate

echo "== second recreate =="
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d --force-recreate

echo "== inspect memberships =="
memberships="$(docker inspect "$CONTAINER_NAME" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}')"
echo "$memberships"

if ! grep -q "$EXTERNAL_NETWORK" <<<"$memberships"; then
  echo "ERROR: external network attachment missing after recreate" >&2
  exit 1
fi

echo "OK: external network still attached after recreate"
