"""Optional Guardrails-AI provider adapter.

This module is intentionally dependency-light: Polis does not import `guardrails` unless the
operator explicitly points `POLIS_GUARDRAILS_PROVIDER_PATH` at `...guardrails_ai_adapter:build`.
Missing package or missing rail configuration fails closed.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from polis.config import get_settings
from polis.modules.model.gateway import ToolCall
from polis.modules.runtime.guardrails import GuardrailSanitizeReport, GuardrailViolation

_FILTERED = "[内容已过滤]"
_FROM_RAIL = "from_rail"
_FROM_RAIL_STRING = "from_rail_string"


class GuardrailsAIProvider:
    """Adapter from Guardrails-AI `Guard.validate()` into Polis GuardrailProvider."""

    name = "guardrails_ai"

    def __init__(self, output_guard: object, *, input_guard: object | None = None) -> None:
        self._output_guard = output_guard
        self._input_guard = input_guard or output_guard

    def check_tool_input(self, tool_call: ToolCall) -> None:
        blob = json.dumps(tool_call.arguments, ensure_ascii=False)
        outcome = _validate(self._input_guard, blob)
        if not _validation_passed(outcome):
            reason = _validation_reason(outcome)
            raise GuardrailViolation(
                f"工具 {tool_call.name} 输入未通过 Guardrails-AI 校验：{reason}"
            )

    def sanitize_with_report(self, output: str) -> GuardrailSanitizeReport:
        outcome = _validate(self._output_guard, output)
        sanitized = _validated_text(outcome, fallback=output)
        if _validation_passed(outcome):
            return _report_for_output(sanitized, changed=sanitized != output)
        if sanitized != output:
            return _report_for_output(sanitized, changed=True)
        return GuardrailSanitizeReport(
            output=_FILTERED,
            injection_matches=1,
            categories={"guardrails_ai_blocked": 1},
        )


def build() -> GuardrailsAIProvider:
    """Build a Guardrails-AI provider from configured rail files."""
    settings = get_settings()
    output_rail_path = getattr(settings, "guardrails_ai_output_rail_path", "")
    input_rail_path = getattr(settings, "guardrails_ai_input_rail_path", "")
    if not output_rail_path:
        raise RuntimeError("Guardrails-AI adapter requires POLIS_GUARDRAILS_AI_OUTPUT_RAIL_PATH")
    output_guard = _load_guard(output_rail_path)
    input_guard = _load_guard(input_rail_path) if input_rail_path else None
    return GuardrailsAIProvider(output_guard, input_guard=input_guard)


def _load_guard(rail_path: str) -> object:
    guard_cls = _guard_class()
    path = Path(rail_path)
    try:
        from_rail = getattr(guard_cls, _FROM_RAIL)
    except AttributeError:
        from_rail = None
    if callable(from_rail):
        return from_rail(str(path))

    try:
        from_rail_string = getattr(guard_cls, _FROM_RAIL_STRING)
    except AttributeError:
        from_rail_string = None
    if callable(from_rail_string):
        return from_rail_string(path.read_text(encoding="utf-8"))

    raise RuntimeError("Guardrails-AI Guard does not expose from_rail/from_rail_string")


def _guard_class() -> type[Any]:
    try:
        guardrails_pkg = importlib.import_module("guardrails")
    except Exception as exc:  # noqa: BLE001 - optional dependency must fail closed.
        raise RuntimeError(
            "Guardrails-AI package is not installed; install guardrails-ai before enabling "
            "polis.modules.runtime.guardrails_ai_adapter:build"
        ) from exc
    guard_cls = getattr(guardrails_pkg, "Guard", None)
    if not isinstance(guard_cls, type):
        raise RuntimeError("Guardrails-AI package does not expose Guard")
    return guard_cls


def _validate(guard: object, text: str) -> object:
    validate = getattr(guard, "validate", None)
    if not callable(validate):
        raise RuntimeError("Guardrails-AI Guard does not expose validate()")
    return validate(text)


def _validation_passed(outcome: object) -> bool:
    if isinstance(outcome, bool):
        return outcome
    for attr in ("validation_passed", "passed", "valid"):
        value = getattr(outcome, attr, None)
        if isinstance(value, bool):
            return value
    return True


def _validated_text(outcome: object, *, fallback: str) -> str:
    if isinstance(outcome, str):
        return outcome
    for attr in ("validated_output", "validated_response", "output"):
        value = getattr(outcome, attr, None)
        if isinstance(value, str):
            return value
    return fallback


def _validation_reason(outcome: object) -> str:
    for attr in ("error", "errors", "validation_summaries"):
        value = getattr(outcome, attr, None)
        if value:
            return str(value)
    return "blocked"


def _report_for_output(output: str, *, changed: bool) -> GuardrailSanitizeReport:
    if not changed:
        return GuardrailSanitizeReport(output=output)
    return GuardrailSanitizeReport(
        output=output,
        pii_matches=1,
        categories={"guardrails_ai_repaired": 1},
    )
