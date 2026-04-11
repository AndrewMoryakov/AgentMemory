#!/usr/bin/env sh
set -eu

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VENV_PYTHON="$BASE_DIR/.venv/bin/python"
WINDOWS_VENV_PYTHON="$BASE_DIR/.venv/Scripts/python.exe"

if [ -x "$VENV_PYTHON" ]; then
  exec "$VENV_PYTHON" "$@"
fi

if [ -f "$WINDOWS_VENV_PYTHON" ]; then
  exec "$WINDOWS_VENV_PYTHON" "$@"
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$@"
fi

exec python "$@"
