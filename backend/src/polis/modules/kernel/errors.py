"""Stable errors for the V3 kernel protocol layer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProtocolIssue:
    """A machine-readable validation or evaluation issue."""

    code: str
    path: str
    message: str


class KernelProtocolError(ValueError):
    """Raised when declarative input violates a stable kernel contract."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.issue = ProtocolIssue(code=code, path=path, message=message)
        super().__init__(f"{code} at {path or '/'}: {message}")

    @property
    def code(self) -> str:
        return self.issue.code

    @property
    def path(self) -> str:
        return self.issue.path


__all__ = ["KernelProtocolError", "ProtocolIssue"]
