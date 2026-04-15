import argparse
import json
import logging
import sys

from agentmemory.formatting import (
    format_delete,
    format_error,
    format_health,
    format_memory,
    format_memory_list,
    format_scopes,
)
from agentmemory.runtime.operation_adapters import cli_operation_source
from agentmemory.runtime.operations import OPERATIONS
from agentmemory.providers.base import ProviderError, ProviderValidationError

logger = logging.getLogger(__name__)


def _use_json(args: argparse.Namespace) -> bool:
    if getattr(args, "json", False):
        return True
    return not (hasattr(sys.stdout, "isatty") and sys.stdout.isatty())


def print_json(data):
    print(json.dumps(data, ensure_ascii=True, indent=2, default=str))


def parse_metadata(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderValidationError(f"Invalid JSON: {exc.msg}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentMemory shared runtime CLI")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health")

    list_scopes_parser = subparsers.add_parser("list-scopes")
    list_scopes_parser.add_argument("--limit", type=int, default=200)
    list_scopes_parser.add_argument("--kind", choices=["user", "agent", "run"])
    list_scopes_parser.add_argument("--query")

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("--user-id")
    add_parser.add_argument("--agent-id")
    add_parser.add_argument("--run-id")
    add_parser.add_argument("--message", action="append", required=True, help="User message text. Repeat to add multiple user messages.")
    add_parser.add_argument("--metadata")
    add_parser.add_argument("--no-infer", action="store_true")
    add_parser.add_argument("--memory-type")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--user-id")
    search_parser.add_argument("--agent-id")
    search_parser.add_argument("--run-id")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--threshold", type=float)
    search_parser.add_argument("--filters")
    search_parser.add_argument("--no-rerank", action="store_true")

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--user-id")
    list_parser.add_argument("--agent-id")
    list_parser.add_argument("--run-id")
    list_parser.add_argument("--limit", type=int, default=100)
    list_parser.add_argument("--filters")

    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("memory_id")

    update_parser = subparsers.add_parser("update")
    update_parser.add_argument("memory_id")
    update_parser.add_argument("data")
    update_parser.add_argument("--metadata")

    delete_parser = subparsers.add_parser("delete")
    delete_parser.add_argument("memory_id")

    args = parser.parse_args()
    use_json = _use_json(args)

    try:
        if args.command == "health":
            result = OPERATIONS["health"].execute(cli_operation_source("health", args, parse_json_arg=parse_metadata))
            print_json(result) if use_json else print(format_health(result))
            return 0
        if args.command == "add":
            result = OPERATIONS["add"].execute(cli_operation_source("add", args, parse_json_arg=parse_metadata))
            print_json(result) if use_json else print(format_memory(result))
            return 0
        if args.command == "list-scopes":
            result = OPERATIONS["list_scopes"].execute(cli_operation_source("list-scopes", args, parse_json_arg=parse_metadata))
            print_json(result) if use_json else print(format_scopes(result))
            return 0
        if args.command == "search":
            result = OPERATIONS["search"].execute(cli_operation_source("search", args, parse_json_arg=parse_metadata))
            print_json(result) if use_json else print(format_memory_list(result, show_score=True))
            return 0
        if args.command == "list":
            result = OPERATIONS["list"].execute(cli_operation_source("list", args, parse_json_arg=parse_metadata))
            print_json(result) if use_json else print(format_memory_list(result))
            return 0
        if args.command == "get":
            result = OPERATIONS["get"].execute(cli_operation_source("get", args, parse_json_arg=parse_metadata))
            print_json(result) if use_json else print(format_memory(result))
            return 0
        if args.command == "update":
            result = OPERATIONS["update"].execute(cli_operation_source("update", args, parse_json_arg=parse_metadata))
            print_json(result) if use_json else print(format_memory(result))
            return 0
        if args.command == "delete":
            result = OPERATIONS["delete"].execute(cli_operation_source("delete", args, parse_json_arg=parse_metadata))
            print_json(result) if use_json else print(format_delete(result))
            return 0
    except ProviderError as exc:
        if use_json:
            print(json.dumps({"error": str(exc), "error_type": type(exc).__name__}, ensure_ascii=True, indent=2), file=sys.stderr)
        else:
            print(format_error(exc, command=args.command), file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
