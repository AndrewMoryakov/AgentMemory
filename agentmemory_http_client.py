from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agentmemory_platform import launcher_command, launcher_path
from agentmemory_runtime import BASE_DIR, ConfigurationError, active_provider_name, current_api_host, current_api_port


OWNER_ENV = "AGENTMEMORY_OWNER_PROCESS"
START_API = launcher_path(BASE_DIR, "start-agentmemory-api")
API_START_TIMEOUT_SECONDS = 20.0


def should_proxy_to_api() -> bool:
    return active_provider_name() == "mem0" and os.environ.get(OWNER_ENV) != "1"


def api_base_url() -> str:
    return f"http://{current_api_host()}:{current_api_port()}"


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {"Accept": "application/json"}
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
            payload = json.loads(body.decode("utf-8"))
            message = payload.get("error", str(exc))
        except Exception:
            message = str(exc)
        raise ConfigurationError(message) from exc
    except URLError as exc:
        raise ConfigurationError(f"AgentMemory API is not reachable at {api_base_url()}. Start it with `agentmemory start-api`.") from exc

    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def api_is_healthy() -> bool:
    try:
        payload = _request("GET", "/health")
    except ConfigurationError:
        return False
    return bool(payload.get("ok"))


def ensure_api_running() -> None:
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

    deadline = time.time() + API_START_TIMEOUT_SECONDS
    while time.time() < deadline:
        if api_is_healthy():
            return
        time.sleep(0.5)

    raise ConfigurationError(f"AgentMemory API did not become ready at {api_base_url()} within {API_START_TIMEOUT_SECONDS:.0f}s")


def proxy_health() -> dict[str, Any]:
    ensure_api_running()
    return _request("GET", "/health")


def proxy_add(*, messages, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None):
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


def proxy_search(*, query, user_id=None, agent_id=None, run_id=None, limit=10, filters=None, threshold=None, rerank=True):
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


def proxy_list(*, user_id=None, agent_id=None, run_id=None, limit=100, filters=None):
    ensure_api_running()
    query = urlencode(
        {
            key: value
            for key, value in {
                "user_id": user_id,
                "agent_id": agent_id,
                "run_id": run_id,
                "limit": limit,
            }.items()
            if value is not None
        }
    )
    path = "/memories"
    if query:
        path = f"{path}?{query}"
    if filters:
        raise ConfigurationError("Filtering through the Mem0 API proxy is not implemented for list yet.")
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
