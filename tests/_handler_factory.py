"""Shared factory for constructing a bare ``Handler`` instance suitable
for invoking ``do_GET``/``do_POST`` from tests without spinning up an
actual HTTP server."""

import io
from typing import Optional

import agentmemory.api as agentmemory_api


def make_handler(
    *,
    path: str,
    method: str = "GET",
    body: bytes = b"{}",
    headers: Optional[dict[str, str]] = None,
    client_address: tuple[str, int] = ("127.0.0.1", 0),
):
    handler = agentmemory_api.Handler.__new__(agentmemory_api.Handler)
    handler.path = path
    handler.headers = {"Content-Length": str(len(body)), **(headers or {})}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.client_address = client_address
    return handler
