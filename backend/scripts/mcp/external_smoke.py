"""Smoke-test a deployed external MCP server.

Examples:
  uv run python scripts/mcp/external_smoke.py --server browser-pilot --transport sse \
    --url http://localhost:8765/sse
  uv run python scripts/mcp/external_smoke.py --server browser-pilot --transport streamable_http \
    --url http://localhost:8765/mcp --call-tool web_search --tool-args '{"q":"polis"}'
  POLIS_MCP_STDIO_ALLOWED_COMMANDS='["uvx"]' uv run python scripts/mcp/external_smoke.py \
    --server browser-pilot --transport stdio --command uvx --arg browser-pilot-mcp
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from polis.modules.runtime.mcp import McpServerConfig, McpToolCallError
from polis.modules.runtime.mcp_smoke import run_external_mcp_smoke


def _json_object(value: str, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be valid JSON object") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError(f"{label} must be valid JSON object")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover and optionally call an external MCP server"
    )
    parser.add_argument(
        "--server",
        required=True,
        help="Logical MCP server name, e.g. browser-pilot",
    )
    parser.add_argument(
        "--transport",
        required=True,
        choices=("stdio", "sse", "streamable_http"),
        help="MCP SDK transport",
    )
    parser.add_argument("--url", help="SSE or Streamable HTTP endpoint URL")
    parser.add_argument(
        "--command",
        help="stdio command; must be allowlisted by POLIS_MCP_STDIO_ALLOWED_COMMANDS",
    )
    parser.add_argument(
        "--arg",
        action="append",
        default=[],
        help="stdio command argument; repeatable",
    )
    parser.add_argument("--env", default="{}", help="stdio env JSON object; values are not printed")
    parser.add_argument(
        "--headers",
        default="{}",
        help="HTTP/SSE headers JSON object; values are not printed",
    )
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--sse-read-timeout-seconds", type=float, default=None)
    parser.add_argument("--call-tool", default=None, help="Optional discovered tool name to call")
    parser.add_argument("--tool-args", default="{}", help="JSON object arguments for --call-tool")
    parser.add_argument("--preview-chars", type=int, default=500)
    return parser


async def _run(args: argparse.Namespace) -> int:
    env = _json_object(args.env, label="--env")
    headers = _json_object(args.headers, label="--headers")
    tool_args = _json_object(args.tool_args, label="--tool-args")
    config = McpServerConfig(
        server=args.server,
        transport=args.transport,
        url=args.url,
        command=args.command,
        args=[str(arg) for arg in args.arg],
        env={str(k): str(v) for k, v in env.items()},
        headers={str(k): str(v) for k, v in headers.items()},
        timeout_seconds=args.timeout_seconds,
        sse_read_timeout_seconds=args.sse_read_timeout_seconds,
    )
    try:
        result = await run_external_mcp_smoke(
            config,
            call_tool=args.call_tool,
            tool_args=tool_args,
            preview_chars=args.preview_chars,
        )
    except McpToolCallError as exc:
        print(f"MCP external smoke: FAIL ({exc})")
        return 1

    print(f"MCP external smoke: PASS server={result.server} transport={result.transport}")
    print(f"Discovered tools: {len(result.tools)}")
    for tool in result.tools:
        print(f"- {tool}")
    if result.called_tool is not None:
        print(f"Called tool: {result.called_tool}")
        print(f"Result preview: {result.call_result_preview or ''}")
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
