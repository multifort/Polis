"""Tiny Streamable HTTP MCP server used by Polis integration tests."""

from __future__ import annotations

import argparse
from contextlib import suppress

from mcp.server.fastmcp import FastMCP


def build_server(port: int) -> FastMCP:
    server = FastMCP(
        "polis-streamable-http-test",
        host="127.0.0.1",
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        log_level="ERROR",
    )

    @server.tool(description="Echo text with a stable HTTP prefix")
    def echo_http(text: str) -> str:
        return f"http-echo:{text}"

    @server.tool(description="Multiply two integers")
    def multiply(a: int, b: int) -> int:
        return a * b

    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with suppress(KeyboardInterrupt):
        build_server(args.port).run("streamable-http")


if __name__ == "__main__":
    main()
