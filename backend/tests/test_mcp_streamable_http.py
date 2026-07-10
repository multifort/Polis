"""Real Streamable HTTP MCP server discovery and call integration."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from polis.modules.runtime.mcp import McpServerConfig
from polis.modules.runtime.mcp_smoke import (
    run_external_mcp_smoke,
    validate_mcp_smoke_evidence,
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(process: subprocess.Popen[bytes], port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Streamable HTTP MCP test server exited during startup")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError("Streamable HTTP MCP test server did not become ready")


@pytest.fixture
def streamable_http_url() -> Iterator[str]:
    port = _free_port()
    server_path = Path(__file__).parent / "fixtures" / "mcp_streamable_http_test_server.py"
    env = os.environ.copy()
    no_proxy = {item for item in env.get("NO_PROXY", "").split(",") if item}
    no_proxy.update({"127.0.0.1", "localhost"})
    env["NO_PROXY"] = ",".join(sorted(no_proxy))
    env["no_proxy"] = env["NO_PROXY"]
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, str(server_path), "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(process, port)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_external_smoke_discovers_and_calls_real_streamable_http_server(
    streamable_http_url: str,
) -> None:
    async def _run() -> dict[str, object]:
        result = await run_external_mcp_smoke(
            McpServerConfig(
                server="polis-streamable-http-test",
                transport="streamable_http",
                url=streamable_http_url,
                timeout_seconds=5.0,
                sse_read_timeout_seconds=5.0,
            ),
            call_tool="echo_http",
            tool_args={"text": "ok"},
        )
        return result.to_evidence()

    evidence = asyncio.run(_run())

    validate_mcp_smoke_evidence(
        evidence,
        expected_server="polis-streamable-http-test",
        expected_transport="streamable_http",
        require_tool="multiply",
        require_called_tool="echo_http",
    )
    assert evidence["discovered_tools"] == ["echo_http", "multiply"]
    assert evidence["call_result_preview"] == "http-echo:ok"
    assert "headers" not in evidence
    assert "env" not in evidence
