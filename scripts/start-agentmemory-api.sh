#!/usr/bin/env sh
set -eu

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
HOST="${1:-127.0.0.1}"
PORT="${2:-8765}"

export AGENTMEMORY_API_HOST="$HOST"
export AGENTMEMORY_API_PORT="$PORT"
export AGENTMEMORY_OWNER_PROCESS="1"

exec "$BASE_DIR/scripts/run-agentmemory-python.sh" -m agentmemory.cli start-api --host "$HOST" --port "$PORT"
