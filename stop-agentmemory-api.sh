#!/usr/bin/env sh
set -eu

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PID_FILE="$BASE_DIR/data/agentmemory-api.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "AgentMemory API PID file not found."
  exit 0
fi

PROCESS_ID=$(cat "$PID_FILE" 2>/dev/null || true)
if [ -n "${PROCESS_ID:-}" ] && kill -0 "$PROCESS_ID" 2>/dev/null; then
  kill "$PROCESS_ID" 2>/dev/null || true
  echo "Stopped AgentMemory API process $PROCESS_ID"
else
  echo "AgentMemory API process is not running."
fi

rm -f "$PID_FILE"
