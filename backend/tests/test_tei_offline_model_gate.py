from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.tei.offline_model_gate import (
    TeiOfflineModelGateError,
    check_offline_model,
    validate_offline_model_evidence,
)

_FILES = (
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
)


def _write_model_dir(path: Path, *, hidden_size: int = 1024, model_bytes: int = 8) -> None:
    path.mkdir(parents=True)
    (path / "config.json").write_text(json.dumps({"hidden_size": hidden_size}), encoding="utf-8")
    for name in _FILES:
        (path / name).write_text("{}", encoding="utf-8")
    (path / "pytorch_model.bin").write_bytes(b"x" * model_bytes)


def test_tei_offline_model_gate_accepts_complete_model(tmp_path: Path) -> None:
    model_dir = tmp_path / "bge-large-zh-v1.5"
    _write_model_dir(model_dir, model_bytes=16)

    evidence = check_offline_model(model_dir, min_model_bytes=16)

    assert evidence.ok is True
    assert evidence.hidden_size == 1024
    assert evidence.model_bytes == 16
    assert evidence.missing_files == []
    validate_offline_model_evidence(evidence)


def test_tei_offline_model_gate_rejects_missing_file(tmp_path: Path) -> None:
    model_dir = tmp_path / "bge-large-zh-v1.5"
    _write_model_dir(model_dir)
    (model_dir / "tokenizer.json").unlink()

    evidence = check_offline_model(model_dir, min_model_bytes=1)

    assert evidence.ok is False
    assert evidence.missing_files == ["tokenizer.json"]
    with pytest.raises(TeiOfflineModelGateError, match="missing required files"):
        validate_offline_model_evidence(evidence)


def test_tei_offline_model_gate_rejects_wrong_dimension(tmp_path: Path) -> None:
    model_dir = tmp_path / "bge-large-zh-v1.5"
    _write_model_dir(model_dir, hidden_size=768)

    evidence = check_offline_model(model_dir, min_model_bytes=1)

    assert evidence.ok is False
    assert evidence.hidden_size == 768
    assert "hidden_size mismatch" in (evidence.error or "")


def test_tei_offline_model_gate_rejects_small_weights(tmp_path: Path) -> None:
    model_dir = tmp_path / "bge-large-zh-v1.5"
    _write_model_dir(model_dir, model_bytes=4)

    evidence = check_offline_model(model_dir, min_model_bytes=8)

    assert evidence.ok is False
    assert evidence.model_bytes == 4
    assert "too small" in (evidence.error or "")
