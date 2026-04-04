import argparse
import json
import sys

from agentmemory_http_client import (
    proxy_add,
    proxy_delete,
    proxy_get,
    proxy_health,
    proxy_list,
    proxy_search,
    proxy_update,
    should_proxy_to_api,
)
from agentmemory_runtime import (
    ConfigurationError,
    health,
    memory_add,
    memory_delete,
    memory_get,
    memory_list,
    memory_search,
    memory_update,
)


def print_json(data):
    print(json.dumps(data, ensure_ascii=True, indent=2, default=str))


def parse_metadata(raw):
    return json.loads(raw) if raw else None


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentMemory shared runtime CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health")

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

    try:
        if args.command == "health":
            print_json(proxy_health() if should_proxy_to_api() else health())
            return 0
        if args.command == "add":
            messages = [{"role": "user", "content": text} for text in args.message]
            kwargs = {
                "messages": messages,
                "user_id": args.user_id,
                "agent_id": args.agent_id,
                "run_id": args.run_id,
                "metadata": parse_metadata(args.metadata),
                "infer": not args.no_infer,
                "memory_type": args.memory_type,
            }
            result = proxy_add(**kwargs) if should_proxy_to_api() else memory_add(**kwargs)
            print_json(result)
            return 0
        if args.command == "search":
            kwargs = {
                "query": args.query,
                "user_id": args.user_id,
                "agent_id": args.agent_id,
                "run_id": args.run_id,
                "limit": args.limit,
                "filters": parse_metadata(args.filters),
                "threshold": args.threshold,
                "rerank": not args.no_rerank,
            }
            result = proxy_search(**kwargs) if should_proxy_to_api() else memory_search(**kwargs)
            print_json(result)
            return 0
        if args.command == "list":
            kwargs = {
                "user_id": args.user_id,
                "agent_id": args.agent_id,
                "run_id": args.run_id,
                "limit": args.limit,
                "filters": parse_metadata(args.filters),
            }
            result = proxy_list(**kwargs) if should_proxy_to_api() else memory_list(**kwargs)
            print_json(result)
            return 0
        if args.command == "get":
            print_json(proxy_get(args.memory_id) if should_proxy_to_api() else memory_get(args.memory_id))
            return 0
        if args.command == "update":
            kwargs = {"memory_id": args.memory_id, "data": args.data, "metadata": parse_metadata(args.metadata)}
            print_json(proxy_update(**kwargs) if should_proxy_to_api() else memory_update(**kwargs))
            return 0
        if args.command == "delete":
            print_json(proxy_delete(memory_id=args.memory_id) if should_proxy_to_api() else memory_delete(memory_id=args.memory_id))
            return 0
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
