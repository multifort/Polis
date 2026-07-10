"""Guardrails provider deployment smoke runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from polis.modules.model.gateway import ToolCall
from polis.modules.runtime.guardrails import Guardrails, GuardrailViolation


class GuardrailsSmokeEvidenceError(ValueError):
    """Guardrails smoke evidence does not satisfy the deployment gate."""


@dataclass(frozen=True)
class GuardrailsSmokeResult:
    provider: str
    checked_at: str
    ok: bool = True
    safe_output_changed: bool = False
    unsafe_output_changed: bool = False
    unsafe_output_categories: dict[str, int] = field(default_factory=dict)
    unsafe_tool_input_blocked: bool = False
    error: str | None = None

    def to_evidence(self) -> dict[str, Any]:
        """Return a credential-safe smoke evidence payload."""
        return {
            "ok": self.ok,
            "provider": self.provider,
            "checked_at": self.checked_at,
            "safe_output_changed": self.safe_output_changed,
            "unsafe_output_changed": self.unsafe_output_changed,
            "unsafe_output_categories": self.unsafe_output_categories,
            "unsafe_tool_input_blocked": self.unsafe_tool_input_blocked,
            "error": self.error,
        }


def run_guardrails_smoke(
    guard: Guardrails,
    *,
    safe_output: str,
    unsafe_output: str,
    unsafe_tool_input: str,
) -> GuardrailsSmokeResult:
    """Exercise a configured Guardrails provider without recording raw sample content."""
    try:
        safe_report = guard.sanitize_with_report(safe_output)
        unsafe_report = guard.sanitize_with_report(unsafe_output)
        unsafe_tool_input_blocked = _tool_input_blocked(guard, unsafe_tool_input)
        return GuardrailsSmokeResult(
            provider=guard.provider_name,
            checked_at=_now_iso(),
            safe_output_changed=safe_report.output != safe_output,
            unsafe_output_changed=unsafe_report.output != unsafe_output,
            unsafe_output_categories=unsafe_report.categories,
            unsafe_tool_input_blocked=unsafe_tool_input_blocked,
        )
    except Exception as exc:  # noqa: BLE001 - deployment smoke should return safe diagnostics.
        return failed_guardrails_smoke_evidence(
            provider=guard.provider_name,
            error=type(exc).__name__,
        )


def failed_guardrails_smoke_evidence(
    *,
    provider: str,
    error: str,
) -> GuardrailsSmokeResult:
    return GuardrailsSmokeResult(
        provider=provider,
        checked_at=_now_iso(),
        ok=False,
        error=error,
    )


def validate_guardrails_smoke_evidence(
    evidence: dict[str, Any],
    *,
    expected_provider: str | None = None,
    require_output_change: bool = False,
    require_tool_input_block: bool = False,
) -> None:
    """Validate credential-safe Guardrails smoke evidence."""
    if evidence.get("ok") is not True:
        raise GuardrailsSmokeEvidenceError("Guardrails smoke did not pass")

    provider = evidence.get("provider")
    if not isinstance(provider, str) or not provider:
        raise GuardrailsSmokeEvidenceError("Guardrails smoke evidence missing provider")
    if expected_provider is not None and expected_provider not in provider.split("+"):
        raise GuardrailsSmokeEvidenceError(
            f"Guardrails provider mismatch: expected {expected_provider}, got {provider}"
        )

    checked_at = evidence.get("checked_at")
    if not isinstance(checked_at, str) or not checked_at:
        raise GuardrailsSmokeEvidenceError("Guardrails smoke evidence missing checked_at")
    try:
        datetime.fromisoformat(checked_at)
    except ValueError as exc:
        raise GuardrailsSmokeEvidenceError("Guardrails smoke checked_at is not ISO-8601") from exc

    if evidence.get("safe_output_changed") is True:
        raise GuardrailsSmokeEvidenceError("Guardrails smoke changed safe output")

    if require_output_change and evidence.get("unsafe_output_changed") is not True:
        raise GuardrailsSmokeEvidenceError("Guardrails smoke did not change unsafe output")

    categories = evidence.get("unsafe_output_categories")
    if not isinstance(categories, dict):
        raise GuardrailsSmokeEvidenceError("Guardrails smoke categories must be an object")
    if require_output_change and not categories:
        raise GuardrailsSmokeEvidenceError("Guardrails smoke did not report output categories")

    if require_tool_input_block and evidence.get("unsafe_tool_input_blocked") is not True:
        raise GuardrailsSmokeEvidenceError("Guardrails smoke did not block unsafe tool input")


def _tool_input_blocked(guard: Guardrails, unsafe_tool_input: str) -> bool:
    try:
        guard.check_tool_input(
            ToolCall(id="guardrails-smoke", name="echo", arguments={"text": unsafe_tool_input})
        )
    except GuardrailViolation:
        return True
    return False


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
