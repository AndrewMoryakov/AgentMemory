from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


def resolve_api_base() -> str:
    explicit = os.environ.get("AGENTMEMORY_API_BASE_URL")
    if explicit:
        return explicit
    host = os.environ.get("AGENTMEMORY_API_HOST", "127.0.0.1")
    port = os.environ.get("AGENTMEMORY_API_PORT", "8765")
    return f"http://{host}:{port}"


API_BASE = resolve_api_base()
SCOPE = {"user_id": "examples-http-roundtrip"}


def request(method: str, path: str, payload: dict | None = None):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = Request(API_BASE + path, data=data, method=method, headers=headers)
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    print(f"AgentMemory API: {API_BASE}")
    created = request(
        "POST",
        "/add",
        {
            "messages": [{"role": "user", "content": "The project prefers explicit provider contracts."}],
            **SCOPE,
            "metadata": {"source": "http_python_roundtrip"},
        },
    )
    print("Created memory:")
    print(json.dumps(created, ensure_ascii=True, indent=2))

    listed = request("GET", f"/memories?user_id={SCOPE['user_id']}&limit=5")
    print("\nList result:")
    print(json.dumps(listed, ensure_ascii=True, indent=2))

    searched = request(
        "POST",
        "/search",
        {
            "query": "provider contracts",
            **SCOPE,
            "limit": 5,
            "rerank": False,
        },
    )
    print("\nSearch result:")
    print(json.dumps(searched, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
