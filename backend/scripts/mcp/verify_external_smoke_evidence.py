"""Verify credential-safe external MCP smoke evidence.

Examples:
  uv run python scripts/mcp/verify_external_smoke_evidence.py \
    var/mcp-smoke/browser-pilot.json --server browser-pilot --transport sse
  uv run python scripts/mcp/verify_external_smoke_evidence.py \
    var/mcp-smoke/browser-pilot.json --require-tool web_search --require-called-tool web_search
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from polis.modules.runtime.mcp_smoke import (
    McpSmokeEvidenceError,
    validate_mcp_smoke_evidence,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate external MCP smoke JSON evidence as a deployment gate"
    )
    parser.add_argument("evidence", help="Path to credential-safe JSON evidence")
    parser.add_argument("--server", default=None, help="Expected logical MCP server name")
    parser.add_argument(
        "--transport",
        default=None,
        choices=("stdio", "sse", "streamable_http"),
        help="Expected MCP transport",
    )
    parser.add_argument("--require-tool", default=None, help="Tool that must be discovered")
    parser.add_argument(
        "--require-called-tool",
        default=None,
        help="Tool that must have been called during smoke",
    )
    return parser


def _load_evidence(path: str) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise McpSmokeEvidenceError("external MCP smoke evidence must be a JSON object")
    return raw


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        validate_mcp_smoke_evidence(
            _load_evidence(args.evidence),
            expected_server=args.server,
            expected_transport=args.transport,
            require_tool=args.require_tool,
            require_called_tool=args.require_called_tool,
        )
    except (OSError, json.JSONDecodeError, McpSmokeEvidenceError) as exc:
        print(f"MCP external smoke evidence: FAIL ({exc})")
        raise SystemExit(1) from exc
    print("MCP external smoke evidence: PASS")


if __name__ == "__main__":
    main()
