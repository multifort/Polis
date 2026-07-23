"""RFC 6901 PathV1 parsing and missing-aware lookup."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from polis.modules.kernel.errors import KernelProtocolError

ALLOWED_CONTEXT_ROOTS: Final = frozenset(
    {"command", "work", "scope", "event", "bundle", "actor", "capacity", "approval"}
)


class _Missing:
    __slots__ = ()

    def __repr__(self) -> str:
        return "MISSING"


MISSING: Final = _Missing()


def parse_path(path: str, *, require_context_root: bool = True) -> tuple[str, ...]:
    """Parse a PathV1 string and reject non-RFC-6901 syntax."""

    if path == "":
        return ()
    if not path.startswith("/"):
        raise KernelProtocolError("PATH_INVALID", "", "PathV1 must be empty or start with '/'")

    tokens: list[str] = []
    for raw_token in path[1:].split("/"):
        token: list[str] = []
        index = 0
        while index < len(raw_token):
            char = raw_token[index]
            if char != "~":
                token.append(char)
                index += 1
                continue
            if index + 1 >= len(raw_token) or raw_token[index + 1] not in {"0", "1"}:
                raise KernelProtocolError(
                    "PATH_ESCAPE_INVALID", path, "'~' must be escaped as ~0 or ~1"
                )
            token.append("~" if raw_token[index + 1] == "0" else "/")
            index += 2
        tokens.append("".join(token))

    if require_context_root and tokens[0] not in ALLOWED_CONTEXT_ROOTS:
        raise KernelProtocolError(
            "PATH_ROOT_FORBIDDEN",
            path,
            f"context root '{tokens[0]}' is not allowed",
        )
    return tuple(tokens)


def resolve_path(document: Any, path: str, *, require_context_root: bool = True) -> Any:
    """Resolve a PathV1 value, preserving the null-versus-missing distinction."""

    current = document
    for token in parse_path(path, require_context_root=require_context_root):
        if isinstance(current, Mapping):
            if token not in current:
                return MISSING
            current = current[token]
            continue
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            if len(token) == 1 and token.isascii() and token.isdigit():
                index = 0
            elif token and token[0] != "0" and token.isascii() and token.isdigit():
                index = int(token)
            else:
                return MISSING
            if index >= len(current):
                return MISSING
            current = current[index]
            continue
        return MISSING
    return current


__all__ = ["ALLOWED_CONTEXT_ROOTS", "MISSING", "parse_path", "resolve_path"]
