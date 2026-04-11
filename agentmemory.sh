#!/usr/bin/env sh
set -eu

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$BASE_DIR/scripts/run-agentmemory-python.sh" -m agentmemory "$@"
