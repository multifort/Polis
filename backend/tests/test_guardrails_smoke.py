from __future__ import annotations

import argparse

import pytest
from scripts.guardrails import smoke

from polis.modules.runtime.guardrails import Guardrails, GuardrailSanitizeReport, GuardrailViolation
from polis.modules.runtime.guardrails_smoke import (
    GuardrailsSmokeEvidenceError,
    run_guardrails_smoke,
    validate_guardrails_smoke_evidence,
)


class _Provider:
    name = "guardrails_ai"

    def check_tool_input(self, _tool_call: object) -> None:
        raise GuardrailViolation("blocked")

    def sanitize_with_report(self, output: str) -> GuardrailSanitizeReport:
        if "unsafe" in output:
            return GuardrailSanitizeReport(
                output="[fixed]",
                pii_matches=1,
                categories={"guardrails_ai_repaired": 1},
            )
        return GuardrailSanitizeReport(output=output)


class _BrokenProvider:
    name = "guardrails_ai"

    def check_tool_input(self, _tool_call: object) -> None:
        raise RuntimeError("credential=do-not-record")

    def sanitize_with_report(self, _output: str) -> GuardrailSanitizeReport:
        raise RuntimeError("credential=do-not-record")


def test_guardrails_smoke_records_only_safe_evidence() -> None:
    result = run_guardrails_smoke(
        Guardrails(_Provider()),
        safe_output="clean",
        unsafe_output="unsafe secret",
        unsafe_tool_input="unsafe tool",
    )

    evidence = result.to_evidence()
    assert evidence["ok"] is True
    assert evidence["provider"] == "guardrails_ai"
    assert evidence["safe_output_changed"] is False
    assert evidence["unsafe_output_changed"] is True
    assert evidence["unsafe_tool_input_blocked"] is True
    assert "unsafe secret" not in str(evidence)

    validate_guardrails_smoke_evidence(
        evidence,
        expected_provider="guardrails_ai",
        require_output_change=True,
        require_tool_input_block=True,
    )


def test_guardrails_smoke_failure_evidence_omits_exception_text() -> None:
    result = run_guardrails_smoke(
        Guardrails(_BrokenProvider()),
        safe_output="clean",
        unsafe_output="unsafe secret",
        unsafe_tool_input="unsafe tool",
    )

    evidence = result.to_evidence()
    assert evidence["ok"] is False
    assert evidence["error"] == "RuntimeError"
    assert "credential=do-not-record" not in str(evidence)


@pytest.mark.parametrize(
    ("patch", "match"),
    [
        ({"ok": False}, "did not pass"),
        ({"provider": "rules"}, "provider mismatch"),
        ({"checked_at": "bad"}, "checked_at"),
        ({"safe_output_changed": True}, "changed safe output"),
        ({"unsafe_output_changed": False}, "did not change unsafe output"),
        ({"unsafe_tool_input_blocked": False}, "did not block unsafe tool input"),
    ],
)
def test_guardrails_smoke_evidence_rejects_bad_payloads(
    patch: dict[str, object],
    match: str,
) -> None:
    evidence: dict[str, object] = {
        "ok": True,
        "provider": "guardrails_ai",
        "checked_at": "2026-07-09T10:00:00+00:00",
        "safe_output_changed": False,
        "unsafe_output_changed": True,
        "unsafe_output_categories": {"guardrails_ai_repaired": 1},
        "unsafe_tool_input_blocked": True,
        "error": None,
    }
    evidence.update(patch)

    with pytest.raises(GuardrailsSmokeEvidenceError, match=match):
        validate_guardrails_smoke_evidence(
            evidence,
            expected_provider="guardrails_ai",
            require_output_change=True,
            require_tool_input_block=True,
        )


def test_guardrails_smoke_cli_fails_provider_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke.Guardrails, "from_settings", lambda: Guardrails(_Provider()))
    args = argparse.Namespace(
        expect_provider="rules",
        safe_output="clean",
        unsafe_output="unsafe",
        unsafe_tool_input="unsafe",
        require_output_change=False,
        require_tool_input_block=False,
        json_out=None,
    )

    code = smoke._run(args)

    assert code == 1
    assert "provider mismatch" in capsys.readouterr().out


def test_guardrails_smoke_cli_omits_provider_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def raise_secret() -> Guardrails:
        raise RuntimeError("credential=do-not-record")

    monkeypatch.setattr(smoke.Guardrails, "from_settings", raise_secret)
    args = argparse.Namespace(
        expect_provider="guardrails_ai",
        safe_output="clean",
        unsafe_output="unsafe",
        unsafe_tool_input="unsafe",
        require_output_change=False,
        require_tool_input_block=False,
        json_out=None,
    )

    assert smoke._run(args) == 1
    output = capsys.readouterr().out
    assert "RuntimeError" in output
    assert "credential=do-not-record" not in output


def test_guardrails_smoke_cli_passes_required_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke.Guardrails, "from_settings", lambda: Guardrails(_Provider()))
    args = argparse.Namespace(
        expect_provider="guardrails_ai",
        safe_output="clean",
        unsafe_output="unsafe",
        unsafe_tool_input="unsafe",
        require_output_change=True,
        require_tool_input_block=True,
        json_out=None,
    )

    assert smoke._run(args) == 0
