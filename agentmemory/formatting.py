"""Human-readable output formatters for CLI commands."""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Any


def _is_tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    if not _is_tty():
        return text
    return f"\033[{code}m{text}\033[0m"


def dim(text: str) -> str:
    return _c("2", text)


def bold(text: str) -> str:
    return _c("1", text)


def green(text: str) -> str:
    return _c("32", text)


def yellow(text: str) -> str:
    return _c("33", text)


def red(text: str) -> str:
    return _c("31", text)


def cyan(text: str) -> str:
    return _c("36", text)


def _short_id(full_id: str, length: int = 8) -> str:
    return full_id[:length] if len(full_id) > length else full_id


def _short_ts(ts: str | None) -> str:
    if not ts:
        return dim("—")
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts[:16] if len(ts) > 16 else ts


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _columns(rows: list[list[str]], *, padding: int = 2) -> str:
    if not rows:
        return ""
    col_count = len(rows[0])
    widths = [0] * col_count
    for row in rows:
        for i, cell in enumerate(row):
            visible = cell
            # strip ANSI for width calc
            import re
            visible = re.sub(r"\033\[[0-9;]*m", "", visible)
            widths[i] = max(widths[i], len(visible))

    lines: list[str] = []
    for row in rows:
        parts = []
        for i, cell in enumerate(row):
            import re
            visible_len = len(re.sub(r"\033\[[0-9;]*m", "", cell))
            pad = widths[i] - visible_len + padding
            parts.append(cell + " " * pad)
        lines.append("  " + "".join(parts).rstrip())
    return "\n".join(lines)


# --- Memory record ---

def format_memory(record: dict[str, Any]) -> str:
    mid = record.get("id", "")
    lines = [
        f"  {bold('Memory')} {dim(_short_id(mid))}",
        "",
        f"  {record.get('memory', '')}",
        "",
    ]
    pairs = []
    for key in ("user_id", "agent_id", "run_id"):
        val = record.get(key)
        if val:
            pairs.append((key.replace("_", " ").title(), val))
    pairs.append(("Provider", record.get("provider", "")))
    if record.get("memory_type"):
        pairs.append(("Type", record["memory_type"]))
    pairs.append(("Created", _short_ts(record.get("created_at"))))
    pairs.append(("Updated", _short_ts(record.get("updated_at"))))
    if record.get("metadata"):
        import json
        pairs.append(("Metadata", json.dumps(record["metadata"], ensure_ascii=False)))

    label_width = max(len(k) for k, _ in pairs)
    for label, value in pairs:
        lines.append(f"  {dim(label.ljust(label_width))}  {value}")
    return "\n".join(lines)


# --- Memory list ---

def format_memory_list(records: list[dict[str, Any]], *, show_score: bool = False) -> str:
    if not records:
        return dim("  No memories found.")

    header = []
    if show_score:
        header.append(dim("SCORE"))
    header.extend([dim("ID"), dim("MEMORY"), dim("USER"), dim("UPDATED")])

    rows = [header]
    for r in records:
        row = []
        if show_score:
            score = r.get("score")
            row.append(yellow(f"{score:.2f}") if score is not None else dim("—"))
        row.append(dim(_short_id(r.get("id", ""))))
        row.append(_truncate(r.get("memory", ""), 40))
        row.append(r.get("user_id") or r.get("agent_id") or r.get("run_id") or dim("—"))
        row.append(_short_ts(r.get("updated_at")))
        rows.append(row)

    count = len(records)
    noun = "result" if show_score else "memory"
    suffix = "ies" if noun == "memory" and count != 1 else ("s" if count != 1 and noun != "memory" else "")
    if noun == "memory" and count != 1:
        count_line = f"\n  {dim(f'{count} memories')}"
    elif noun == "memory":
        count_line = f"\n  {dim('1 memory')}"
    else:
        count_line = f"\n  {dim(f'{count} result' + ('s' if count != 1 else ''))}"

    return _columns(rows) + count_line


# --- Scopes ---

def format_scopes(inventory: dict[str, Any]) -> str:
    items = inventory.get("items", [])
    totals = inventory.get("totals", {})

    if not items:
        return dim("  No scopes found.")

    header = [dim("KIND"), dim("VALUE"), dim("COUNT"), dim("LAST SEEN")]
    rows = [header]
    for item in items:
        kind = item["kind"]
        kind_display = cyan(kind) if kind == "user" else yellow(kind) if kind == "agent" else dim(kind)
        rows.append([
            kind_display,
            item["value"],
            str(item["count"]),
            _short_ts(item.get("last_seen_at")),
        ])

    summary = dim(f"  Totals: {totals.get('users', 0)} users, {totals.get('agents', 0)} agents, {totals.get('runs', 0)} runs")
    return _columns(rows) + "\n\n" + summary


# --- Health ---

def format_health(payload: dict[str, Any]) -> str:
    ok = payload.get("ok", False)
    status = green("● healthy") if ok else red("● unhealthy")
    provider = payload.get("provider", "unknown")
    profile = payload.get("active_profile", "default")
    host = payload.get("api_host", "127.0.0.1")
    port = payload.get("api_port", 8765)
    api_status = payload.get("api_runtime", {}).get("status", "unknown")
    api_badge = green("running") if api_status == "running" else yellow(api_status)

    caps = payload.get("capabilities", {})
    search = "semantic" if caps.get("supports_semantic_search") else "text" if caps.get("supports_text_search") else "none"

    lines = [
        f"  {bold('AgentMemory')}  {status}",
        "",
        f"  {dim('Provider')}   {provider}",
        f"  {dim('Profile')}    {profile}",
        f"  {dim('API')}        http://{host}:{port}  {api_badge}",
        f"  {dim('Search')}     {search}",
    ]

    # Provider-specific info
    if payload.get("storage_path"):
        lines.append(f"  {dim('Storage')}    {payload['storage_path']}")
    if payload.get("llm_model"):
        lines.append(f"  {dim('LLM')}        {payload['llm_model']}")

    return "\n".join(lines)


# --- Delete ---

def format_delete(result: dict[str, Any]) -> str:
    mid = result.get("id", "")
    if result.get("deleted"):
        return green(f"  Deleted memory {_short_id(mid)}")
    return red(f"  Failed to delete memory {_short_id(mid)}")


# --- Errors ---

def format_error(exc: Exception, *, command: str = "") -> str:
    error_type = type(exc).__name__
    lines = [red(f"  Error: {exc}")]

    if "not found" in str(exc).lower() or "MemoryNotFound" in error_type:
        lines.append(dim("  Try: agentmemory list --user-id <user> to see available memories"))
    elif "scope" in str(exc).lower() or "ScopeRequired" in error_type:
        lines.append(dim("  This provider requires --user-id, --agent-id, or --run-id"))
    elif "not available" in str(exc).lower() or "Unavailable" in error_type:
        lines.append(dim("  Try: agentmemory doctor to check runtime status"))
    elif "configuration" in str(exc).lower() or "Configuration" in error_type:
        lines.append(dim("  Try: agentmemory configure --provider <name>"))

    return "\n".join(lines)
