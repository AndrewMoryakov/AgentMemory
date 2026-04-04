#!/usr/bin/env sh
set -eu

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE="$BASE_DIR/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

exec "$BASE_DIR/run-agentmemory-python.sh" "$BASE_DIR/agentmemory_mcp_server.py"
