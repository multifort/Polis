"""Closed JSON Schema Draft 2020-12 profile used by V3 definitions."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, ClassVar

from jsonschema import Draft202012Validator, FormatChecker, SchemaError, ValidationError
from pydantic import JsonValue, RootModel, model_validator
from pydantic_core import PydanticCustomError

from polis.modules.kernel.domain.canonical import canonical_json_bytes
from polis.modules.kernel.domain.paths import MISSING, resolve_path
from polis.modules.kernel.errors import KernelProtocolError

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
MAX_SCHEMA_DEPTH = 32
MAX_SCHEMA_NODES = 2_000
MAX_SCHEMA_DEFS = 128
MAX_SCHEMA_BYTES = 256 * 1024

ALLOWED_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$defs",
        "$ref",
        "title",
        "description",
        "type",
        "enum",
        "const",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minProperties",
        "maxProperties",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "format",
    }
)
ALLOWED_FORMATS = frozenset({"uuid", "date-time", "date", "email", "uri"})
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$")
_FORMAT_CHECKER = FormatChecker()


@_FORMAT_CHECKER.checks("date-time")
def _is_strict_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if _RFC3339.fullmatch(value) is None:
        return False
    try:
        normalized = value.replace("t", "T").replace("z", "Z").replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).tzinfo is not None
    except ValueError:
        return False


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _child_path(path: str, token: str) -> str:
    return f"{path}/{_escape(token)}"


def _subschemas(schema: Mapping[str, Any], path: str) -> Iterable[tuple[Mapping[str, Any], str]]:
    for container_key in ("$defs", "properties"):
        container = schema.get(container_key)
        if isinstance(container, Mapping):
            for key, child in container.items():
                if isinstance(child, Mapping):
                    yield child, _child_path(_child_path(path, container_key), str(key))
    items = schema.get("items")
    if isinstance(items, Mapping):
        yield items, _child_path(path, "items")
    additional = schema.get("additionalProperties")
    if isinstance(additional, Mapping):
        yield additional, _child_path(path, "additionalProperties")
    for container_key in ("allOf", "anyOf", "oneOf"):
        container = schema.get(container_key)
        if isinstance(container, list):
            for index, child in enumerate(container):
                if isinstance(child, Mapping):
                    yield child, f"{_child_path(path, container_key)}/{index}"
    negated = schema.get("not")
    if isinstance(negated, Mapping):
        yield negated, _child_path(path, "not")


def _inspect_schema(schema: Mapping[str, Any]) -> None:
    node_count = 0
    references: list[tuple[str, str]] = []

    def walk(node: Mapping[str, Any], path: str, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if depth > MAX_SCHEMA_DEPTH:
            raise KernelProtocolError(
                "SCHEMA_DEPTH_EXCEEDED", path, f"schema depth exceeds {MAX_SCHEMA_DEPTH}"
            )
        if node_count > MAX_SCHEMA_NODES:
            raise KernelProtocolError(
                "SCHEMA_NODE_LIMIT_EXCEEDED", path, f"schema nodes exceed {MAX_SCHEMA_NODES}"
            )
        for keyword in node:
            if keyword not in ALLOWED_SCHEMA_KEYWORDS:
                raise KernelProtocolError(
                    "SCHEMA_KEYWORD_UNSUPPORTED",
                    _child_path(path, keyword),
                    f"JSON Schema keyword '{keyword}' is not supported",
                )
        schema_uri = node.get("$schema")
        if schema_uri is not None and schema_uri != DRAFT_2020_12:
            raise KernelProtocolError(
                "SCHEMA_DIALECT_UNSUPPORTED",
                _child_path(path, "$schema"),
                f"$schema must equal {DRAFT_2020_12}",
            )
        schema_format = node.get("format")
        if schema_format is not None and schema_format not in ALLOWED_FORMATS:
            raise KernelProtocolError(
                "SCHEMA_FORMAT_UNSUPPORTED",
                _child_path(path, "format"),
                f"format '{schema_format}' is not supported",
            )
        schema_type = node.get("type")
        object_schema = schema_type == "object" or (
            isinstance(schema_type, list) and "object" in schema_type
        )
        if object_schema and "additionalProperties" not in node:
            raise KernelProtocolError(
                "SCHEMA_ADDITIONAL_PROPERTIES_REQUIRED",
                path,
                "object schemas must declare additionalProperties explicitly",
            )
        reference = node.get("$ref")
        if reference is not None:
            if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
                raise KernelProtocolError(
                    "SCHEMA_REF_FORBIDDEN",
                    _child_path(path, "$ref"),
                    "$ref must target the current schema under #/$defs/",
                )
            references.append((reference, _child_path(path, "$ref")))
        for child, child_path in _subschemas(node, path):
            walk(child, child_path, depth + 1)

    walk(schema, "", 1)
    definitions = schema.get("$defs", {})
    if isinstance(definitions, Mapping) and len(definitions) > MAX_SCHEMA_DEFS:
        raise KernelProtocolError(
            "SCHEMA_DEFS_LIMIT_EXCEEDED", "/$defs", f"$defs exceeds {MAX_SCHEMA_DEFS} entries"
        )
    if len(canonical_json_bytes(schema)) > MAX_SCHEMA_BYTES:
        raise KernelProtocolError(
            "SCHEMA_SIZE_EXCEEDED", "", f"canonical schema exceeds {MAX_SCHEMA_BYTES} bytes"
        )

    for reference, path in references:
        target = resolve_path(schema, reference[1:], require_context_root=False)
        if target is MISSING:
            raise KernelProtocolError(
                "SCHEMA_REF_NOT_FOUND", path, f"reference '{reference}' not found"
            )

    graph: dict[str, set[str]] = {}
    if isinstance(definitions, Mapping):
        for definition_key, definition in definitions.items():
            if not isinstance(definition, Mapping):
                continue
            targets: set[str] = set()
            stack = [definition]
            while stack:
                current = stack.pop()
                current_reference = current.get("$ref")
                if isinstance(current_reference, str) and current_reference.startswith("#/$defs/"):
                    target_token = current_reference.removeprefix("#/$defs/").split("/", 1)[0]
                    targets.add(target_token.replace("~1", "/").replace("~0", "~"))
                stack.extend(child for child, _ in _subschemas(current, ""))
            graph[str(definition_key)] = targets

    visiting: set[str] = set()
    visited: set[str] = set()

    def check_cycle(key: str, chain: tuple[str, ...]) -> None:
        if key in visiting:
            cycle = " -> ".join((*chain, key))
            raise KernelProtocolError(
                "SCHEMA_REF_RECURSIVE", f"/$defs/{_escape(key)}", f"recursive $ref: {cycle}"
            )
        if key in visited:
            return
        visiting.add(key)
        for target in sorted(graph.get(key, set())):
            check_cycle(target, (*chain, key))
        visiting.remove(key)
        visited.add(key)

    for definition_key in sorted(graph):
        check_cycle(definition_key, ())

    try:
        Draft202012Validator.check_schema(dict(schema))
    except SchemaError as exc:
        path = "".join(f"/{_escape(str(token))}" for token in exc.absolute_path)
        raise KernelProtocolError("SCHEMA_INVALID", path, exc.message) from exc


class SchemaProfileV1(RootModel[dict[str, JsonValue]]):
    """A JSON Schema constrained to the V3 closed keyword profile."""

    format_checker: ClassVar[FormatChecker] = _FORMAT_CHECKER

    @model_validator(mode="before")
    @classmethod
    def validate_profile(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            raise PydanticCustomError("SCHEMA_INVALID", "schema must be an object", {"path": ""})
        try:
            _inspect_schema(value)
        except KernelProtocolError as exc:
            raise PydanticCustomError(
                exc.code,
                exc.issue.message,
                {"path": exc.path},
            ) from exc
        return value

    def validate_instance(self, value: Any) -> None:
        """Validate a business value with format assertions enabled."""

        validator = Draft202012Validator(self.root, format_checker=self.format_checker)
        errors = sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path))
        if not errors:
            return
        error: ValidationError = errors[0]
        path = "".join(f"/{_escape(str(token))}" for token in error.absolute_path)
        raise KernelProtocolError("SCHEMA_INSTANCE_INVALID", path, error.message)


__all__ = [
    "ALLOWED_FORMATS",
    "ALLOWED_SCHEMA_KEYWORDS",
    "DRAFT_2020_12",
    "MAX_SCHEMA_BYTES",
    "MAX_SCHEMA_DEFS",
    "MAX_SCHEMA_DEPTH",
    "MAX_SCHEMA_NODES",
    "SchemaProfileV1",
]
