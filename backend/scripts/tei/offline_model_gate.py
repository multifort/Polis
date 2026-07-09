"""Verify the offline TEI embedding model mount.

Examples:
  uv run python scripts/tei/offline_model_gate.py
  uv run python scripts/tei/offline_model_gate.py \
    --model-dir ../infra/tei-models/bge-large-zh-v1.5 \
    --json-out var/tei-offline-model.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MODEL_NAME = "bge-large-zh-v1.5"
_EXPECTED_HIDDEN_SIZE = 1024
_DEFAULT_MIN_MODEL_BYTES = 1_000_000_000
_REQUIRED_FILES = (
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "pytorch_model.bin",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
)


class TeiOfflineModelGateError(ValueError):
    """Offline TEI model directory does not satisfy the deployment gate."""


@dataclass(frozen=True)
class TeiOfflineModelEvidence:
    ok: bool
    model_dir: str
    model_name: str
    hidden_size: int | None
    model_bytes: int
    required_files: list[str]
    missing_files: list[str]
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "model_dir": self.model_dir,
            "model_name": self.model_name,
            "hidden_size": self.hidden_size,
            "model_bytes": self.model_bytes,
            "required_files": self.required_files,
            "missing_files": self.missing_files,
            "error": self.error,
        }


def check_offline_model(
    model_dir: Path,
    *,
    expected_hidden_size: int = _EXPECTED_HIDDEN_SIZE,
    min_model_bytes: int = _DEFAULT_MIN_MODEL_BYTES,
) -> TeiOfflineModelEvidence:
    model_dir = model_dir.resolve()
    missing = [name for name in _REQUIRED_FILES if not (model_dir / name).is_file()]
    if missing:
        return _failed(model_dir, missing, f"missing required files: {', '.join(missing)}")

    config = _load_config(model_dir / "config.json")
    hidden_size = config.get("hidden_size")
    if hidden_size != expected_hidden_size:
        return _failed(
            model_dir,
            missing,
            f"hidden_size mismatch: expected {expected_hidden_size}, got {hidden_size}",
            hidden_size=hidden_size if isinstance(hidden_size, int) else None,
        )

    model_bytes = (model_dir / "pytorch_model.bin").stat().st_size
    if model_bytes < min_model_bytes:
        return _failed(
            model_dir,
            missing,
            f"model file too small: expected >= {min_model_bytes} bytes, got {model_bytes}",
            hidden_size=hidden_size,
            model_bytes=model_bytes,
        )

    return TeiOfflineModelEvidence(
        ok=True,
        model_dir=str(model_dir),
        model_name=_MODEL_NAME,
        hidden_size=hidden_size,
        model_bytes=model_bytes,
        required_files=list(_REQUIRED_FILES),
        missing_files=[],
    )


def validate_offline_model_evidence(evidence: TeiOfflineModelEvidence) -> None:
    if not evidence.ok:
        raise TeiOfflineModelGateError(evidence.error or "TEI offline model gate failed")
    if evidence.hidden_size != _EXPECTED_HIDDEN_SIZE:
        raise TeiOfflineModelGateError("TEI offline model evidence has unexpected hidden_size")
    if evidence.missing_files:
        raise TeiOfflineModelGateError("TEI offline model evidence has missing files")


def _failed(
    model_dir: Path,
    missing: list[str],
    error: str,
    *,
    hidden_size: int | None = None,
    model_bytes: int = 0,
) -> TeiOfflineModelEvidence:
    return TeiOfflineModelEvidence(
        ok=False,
        model_dir=str(model_dir),
        model_name=_MODEL_NAME,
        hidden_size=hidden_size,
        model_bytes=model_bytes,
        required_files=list(_REQUIRED_FILES),
        missing_files=missing,
        error=error,
    )


def _load_config(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TeiOfflineModelGateError(f"cannot read TEI config: {path}") from exc
    except json.JSONDecodeError as exc:
        raise TeiOfflineModelGateError(f"TEI config is not valid JSON: {path}") from exc
    if not isinstance(raw, dict):
        raise TeiOfflineModelGateError(f"TEI config must be a JSON object: {path}")
    return raw


def _default_model_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "infra" / "tei-models" / _MODEL_NAME


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify offline TEI model files")
    parser.add_argument("--model-dir", type=Path, default=_default_model_dir())
    parser.add_argument("--expected-hidden-size", type=int, default=_EXPECTED_HIDDEN_SIZE)
    parser.add_argument("--min-model-bytes", type=int, default=_DEFAULT_MIN_MODEL_BYTES)
    parser.add_argument("--json-out", default=None)
    return parser


def _write_json_out(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    args = _build_parser().parse_args()
    try:
        evidence = check_offline_model(
            args.model_dir,
            expected_hidden_size=args.expected_hidden_size,
            min_model_bytes=args.min_model_bytes,
        )
        validate_offline_model_evidence(evidence)
    except TeiOfflineModelGateError as exc:
        evidence = _failed(args.model_dir.resolve(), [], str(exc))
        _write_json_out(args.json_out, evidence.to_json())
        print(f"TEI offline model gate: FAIL ({exc})")
        raise SystemExit(1) from exc

    _write_json_out(args.json_out, evidence.to_json())
    print(
        "TEI offline model gate: PASS "
        f"model={evidence.model_name} hidden_size={evidence.hidden_size} "
        f"bytes={evidence.model_bytes}"
    )


if __name__ == "__main__":
    main()
