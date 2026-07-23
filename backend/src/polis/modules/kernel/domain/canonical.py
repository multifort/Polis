"""RFC 8785 canonical JSON and kernel checksum helpers."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

import rfc8785

from polis.modules.kernel.errors import KernelProtocolError

MAX_SAFE_INTEGER = 2**53 - 1


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def validate_json_value(value: Any, *, path: str = "") -> None:
    """Reject values outside the V3 JSON number and container contract."""

    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise KernelProtocolError(
                "JSON_INTEGER_OUT_OF_RANGE",
                path,
                "integer exceeds the IEEE-754 safe integer range",
            )
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise KernelProtocolError(
                "JSON_NUMBER_NON_FINITE", path, "NaN and Infinity are forbidden"
            )
        if value == 0.0 and math.copysign(1.0, value) < 0:
            raise KernelProtocolError("JSON_NEGATIVE_ZERO", path, "negative zero is forbidden")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise KernelProtocolError(
                    "JSON_OBJECT_KEY_INVALID", path, "object keys must be strings"
                )
            validate_json_value(child, path=f"{path}/{_pointer_token(key)}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            validate_json_value(child, path=f"{path}/{index}")
        return
    raise KernelProtocolError(
        "JSON_TYPE_UNSUPPORTED", path, f"{type(value).__name__} is not a JSON value"
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return the one canonical byte representation allowed by the kernel."""

    validate_json_value(value)
    try:
        return rfc8785.dumps(value)
    except rfc8785.CanonicalizationError as exc:
        raise KernelProtocolError("JSON_CANONICALIZATION_FAILED", "", str(exc)) from exc


def canonical_checksum(value: Any) -> str:
    """Return an RFC 8785 + SHA-256 lower-case checksum."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = [
    "MAX_SAFE_INTEGER",
    "canonical_checksum",
    "canonical_json_bytes",
    "validate_json_value",
]
