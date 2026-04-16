"""Session scope persistence for CLI commands."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentmemory.runtime.config import RUNTIME_DIR

SCOPE_FILE = RUNTIME_DIR / "scope.json"

SCOPE_KEYS = ("user_id", "agent_id", "run_id")


def load_scope() -> dict[str, str | None]:
    if not SCOPE_FILE.exists():
        return {k: None for k in SCOPE_KEYS}
    try:
        data = json.loads(SCOPE_FILE.read_text(encoding="utf-8"))
        return {k: data.get(k) for k in SCOPE_KEYS}
    except (OSError, ValueError):
        return {k: None for k in SCOPE_KEYS}


def save_scope(*, user_id: str | None = None, agent_id: str | None = None, run_id: str | None = None) -> dict[str, str | None]:
    scope = {"user_id": user_id, "agent_id": agent_id, "run_id": run_id}
    SCOPE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCOPE_FILE.write_text(json.dumps(scope, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return scope


def clear_scope() -> None:
    SCOPE_FILE.unlink(missing_ok=True)


def has_scope() -> bool:
    scope = load_scope()
    return any(v is not None for v in scope.values())


def scope_label() -> str:
    scope = load_scope()
    parts = [f"{v}" for k, v in scope.items() if v is not None]
    return parts[0] if parts else ""


def apply_scope(args: Any) -> None:
    """Fill in missing scope fields from saved scope."""
    scope = load_scope()
    for key in SCOPE_KEYS:
        arg_key = key.replace("_", "-")
        current = getattr(args, key.replace("-", "_"), None)
        if current is None and scope.get(key) is not None:
            setattr(args, key.replace("-", "_"), scope[key])
