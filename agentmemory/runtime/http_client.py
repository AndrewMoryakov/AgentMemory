from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agentmemory.platform import launcher_command, launcher_path
from agentmemory.runtime.config import BASE_DIR, active_provider_runtime_policy, clear_caches, current_api_host, current_api_port
from agentmemory.runtime.transport import error_class_for_type
from agentmemory.providers.base import (
    ProviderError,
    ProviderUnavailableError,
)


OWNER_ENV = "AGENTMEMORY_OWNER_PROCESS"
START_API = launcher_path(BASE_DIR, "start-agentmemory-api")
API_START_TIMEOUT_SECONDS = 20.0
API_START_LOCK_FILE = BASE_DIR / "data" / "agentmemory-api.start.lock"

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def should_proxy_to_api() -> bool:
    transport_mode = active_provider_runtime_policy()["transport_mode"]
    if transport_mode == "remote_only":
        raise ProviderUnavailableError(
            "Provider transport mode 'remote_only' requires a supported remote transport implementation; "
            "local direct execution is not available."
        )
    return transport_mode == "owner_process_proxy" and os.environ.get(OWNER_ENV) != "1"


def api_base_url() -> str:
    return f"http://{current_api_host()}:{current_api_port()}"


def _authorization_header() -> str | None:
    token = os.environ.get("AGENTMEMORY_API_TOKEN", "").strip()
    if not token:
        return None
    return f"Bearer {token}"


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    authorization = _authorization_header()
    if authorization is not None:
        headers["Authorization"] = authorization
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    request = Request(api_base_url() + path, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
    except HTTPError as exc:
        body = exc.read()
        try:
            response_payload = json.loads(body.decode("utf-8"))
            message = response_payload.get("error", str(exc))
            error_type = response_payload.get("error_type", "")
        except Exception:
            message = str(exc)
            error_type = ""
        error_type_cls = error_class_for_type(error_type, status_code=exc.code)
        raise error_type_cls(message) from exc
    except URLError as exc:
        raise ProviderUnavailableError(f"AgentMemory API is not reachable at {api_base_url()}. Start it with `agentmemory start-api`.") from exc

    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def api_is_healthy() -> bool:
    try:
        payload = _request("GET", "/health")
    except ProviderError:
        return False
    return bool(payload.get("ok"))


@contextlib.contextmanager
def _api_start_lock():
    lock_path = Path(API_START_LOCK_FILE)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0)
        if os.name == "nt":
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock_file.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def ensure_api_running() -> None:
    if api_is_healthy():
        return

    with _api_start_lock():
        if api_is_healthy():
            return

        env = os.environ.copy()
        env[OWNER_ENV] = "1"
        subprocess.run(
            [*launcher_command(START_API), current_api_host(), str(current_api_port())],
            check=False,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        clear_caches()

        deadline = time.time() + API_START_TIMEOUT_SECONDS
        while time.time() < deadline:
            if api_is_healthy():
                return
            time.sleep(0.5)

    raise ProviderUnavailableError(f"AgentMemory API did not become ready at {api_base_url()} within {API_START_TIMEOUT_SECONDS:.0f}s")


def proxy_health() -> dict[str, Any]:
    ensure_api_running()
    return _request("GET", "/health")


def proxy_add(*, messages, user_id=None, agent_id=None, run_id=None, metadata=None, infer, memory_type=None):
    ensure_api_running()
    return _request(
        "POST",
        "/add",
        {
            "messages": messages,
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "metadata": metadata,
            "infer": infer,
            "memory_type": memory_type,
        },
    )


def proxy_search(*, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank):
    ensure_api_running()
    return _request(
        "POST",
        "/search",
        {
            "query": query,
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "limit": limit,
            "filters": filters,
            "threshold": threshold,
            "rerank": rerank,
        },
    )


def proxy_search_page(*, query, user_id=None, agent_id=None, run_id=None, limit=10, cursor=None, filters=None, threshold=None, rerank):
    ensure_api_running()
    return _request(
        "POST",
        "/search/page",
        {
            "query": query,
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "limit": limit,
            "cursor": cursor,
            "filters": filters,
            "threshold": threshold,
            "rerank": rerank,
        },
    )


def proxy_list(*, user_id=None, agent_id=None, run_id=None, limit=100, filters=None):
    ensure_api_running()
    query_payload: dict[str, Any] = {
        "user_id": user_id,
        "agent_id": agent_id,
        "run_id": run_id,
        "limit": limit,
    }
    if filters is not None:
        query_payload["filters"] = json.dumps(filters, ensure_ascii=True, separators=(",", ":"))
    query = urlencode(
        {
            key: value
            for key, value in query_payload.items()
            if value is not None
        }
    )
    path = "/memories"
    if query:
        path = f"{path}?{query}"
    return _request("GET", path)


def proxy_list_page(*, user_id=None, agent_id=None, run_id=None, limit=100, cursor=None, filters=None):
    ensure_api_running()
    query_payload: dict[str, Any] = {
        "user_id": user_id,
        "agent_id": agent_id,
        "run_id": run_id,
        "limit": limit,
        "cursor": cursor,
    }
    if filters is not None:
        query_payload["filters"] = json.dumps(filters, ensure_ascii=True, separators=(",", ":"))
    query = urlencode(
        {
            key: value
            for key, value in query_payload.items()
            if value is not None
        }
    )
    path = "/memories/page"
    if query:
        path = f"{path}?{query}"
    return _request("GET", path)


def proxy_get(memory_id: str):
    ensure_api_running()
    return _request("GET", f"/memories/{memory_id}")


def proxy_update(*, memory_id, data, metadata=None):
    ensure_api_running()
    return _request("POST", "/update", {"memory_id": memory_id, "data": data, "metadata": metadata})


def proxy_delete(*, memory_id):
    ensure_api_running()
    return _request("DELETE", f"/memories/{memory_id}")


def proxy_list_scopes(*, limit: int = 200, kind: str | None = None, query: str | None = None):
    ensure_api_running()
    query_payload: dict[str, Any] = {"limit": limit, "kind": kind, "query": query}
    encoded = urlencode({key: value for key, value in query_payload.items() if value is not None})
    path = "/admin/scopes"
    if encoded:
        path = f"{path}?{encoded}"
    return _request("GET", path)


def proxy_list_scopes_page(*, limit: int = 200, cursor: str | None = None, kind: str | None = None, query: str | None = None):
    ensure_api_running()
    query_payload: dict[str, Any] = {"limit": limit, "cursor": cursor, "kind": kind, "query": query}
    encoded = urlencode({key: value for key, value in query_payload.items() if value is not None})
    path = "/admin/scopes/page"
    if encoded:
        path = f"{path}?{encoded}"
    return _request("GET", path)
