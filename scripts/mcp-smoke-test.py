import json
import subprocess
from pathlib import Path

from agentmemory.platform import launcher_command, launcher_path

BASE_DIR = Path(__file__).resolve().parent.parent
SERVER = launcher_path(BASE_DIR, "run-agentmemory-mcp")


def send_request(proc, message):
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def send_notification(proc, message):
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()


def main() -> int:
    proc = subprocess.Popen(
        launcher_command(SERVER),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    try:
        init_response = send_request(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "agentmemory-test-client", "version": "1.0.0"}
            }
        })
        print(json.dumps(init_response, indent=2))

        send_notification(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        tools_response = send_request(proc, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        })
        print(json.dumps(tools_response, indent=2))

        health_response = send_request(proc, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "memory_health", "arguments": {}}
        })
        print(json.dumps(health_response, indent=2))
        return 0
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())

