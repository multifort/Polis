"""Tiny stdio MCP server used by Polis integration tests."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("polis-stdio-test")


@mcp.tool(description="Echo text with a stable prefix")
def echo(text: str) -> str:
    return f"echo:{text}"


@mcp.tool(description="Add two integers")
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    mcp.run("stdio")
