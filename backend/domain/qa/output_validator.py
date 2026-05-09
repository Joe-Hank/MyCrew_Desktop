"""Task output schema validation — schedules Pydantic validation via infra layer."""
from __future__ import annotations

import json
from typing import Any


def validate_output_schema(output: dict[str, Any],
                           schema: dict[str, Any]) -> list[str]:
    """Validate a structured output dict against a JSON Schema.

    Returns a list of error messages. Empty list = valid.
    Uses jsonschema if available, otherwise does basic structural checks.
    """
    if not schema or schema == {}:
        return []

    try:
        import jsonschema
        validator = jsonschema.Draft7Validator(schema)
        return [
            f"{'.'.join(str(p) for p in e.absolute_path)}: {e.message}"
            if e.absolute_path else e.message
            for e in validator.iter_errors(output)
        ]
    except ImportError:
        return _basic_validate(output, schema)


def validate_schema_is_valid(schema: dict[str, Any]) -> list[str]:
    """Check that a schema itself is a valid JSON Schema."""
    if not schema or schema == {}:
        return []

    try:
        import jsonschema
        jsonschema.Draft7Validator.check_schema(schema)
        return []
    except jsonschema.SchemaError as exc:
        return [str(exc.message)]
    except ImportError:
        if not isinstance(schema, dict):
            return ["Schema must be a JSON object"]
        return []


def _basic_validate(output: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Fallback validation when jsonschema is not installed."""
    errors = []
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for field_name in required:
        if field_name not in output:
            errors.append(f"Missing required field: {field_name}")

    for field_name, field_schema in properties.items():
        if field_name not in output:
            continue
        expected_type = field_schema.get("type")
        value = output[field_name]
        if expected_type and not _type_matches(value, expected_type):
            errors.append(
                f"Field '{field_name}': expected type '{expected_type}', "
                f"got '{type(value).__name__}'"
            )

    return errors


_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _type_matches(value: Any, expected: str) -> bool:
    py_type = _TYPE_MAP.get(expected)
    if py_type is None:
        return True
    return isinstance(value, py_type)
