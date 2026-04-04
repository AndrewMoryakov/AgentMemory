#!/usr/bin/env sh
set -eu

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATA_DIR="$BASE_DIR/data"
PID_FILE="$DATA_DIR/agentmemory-api.pid"
LOG_FILE="$DATA_DIR/agentmemory-api.log"
ERR_FILE="$DATA_DIR/agentmemory-api.err.log"
HOST="${1:-127.0.0.1}"
PORT="${2:-8765}"
ENV_FILE="$BASE_DIR/.env"

mkdir -p "$DATA_DIR"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

if [ -f "$PID_FILE" ]; then
  EXISTING_PID=$(cat "$PID_FILE" 2>/dev/null || true)
  if [ -n "${EXISTING_PID:-}" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "AgentMemory API is already running with PID $EXISTING_PID on $HOST:$PORT"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

AGENTMEMORY_API_HOST="$HOST" \
AGENTMEMORY_API_PORT="$PORT" \
AGENTMEMORY_OWNER_PROCESS="1" \
nohup "$BASE_DIR/run-agentmemory-python.sh" "$BASE_DIR/agentmemory_api.py" >>"$LOG_FILE" 2>>"$ERR_FILE" &

API_PID=$!
echo "$API_PID" > "$PID_FILE"
echo "AgentMemory API started with PID $API_PID. Logs: $LOG_FILE, $ERR_FILE"
