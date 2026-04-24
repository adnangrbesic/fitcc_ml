from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator


class StrictSchemaValidator:
    """Strict JSON-schema validator with clear error messages."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self._validator = Draft202012Validator(schema)

    def validate(self, payload: dict[str, Any]) -> None:
        errors = sorted(self._validator.iter_errors(payload), key=lambda e: list(e.path))
        if not errors:
            return

        first = errors[0]
        location = "/".join(str(p) for p in first.path) or "<root>"
        raise ValueError(f"Schema validation failed at {location}: {first.message}")
