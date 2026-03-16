"""Config schema validation for plugins.

Validates plugin config dicts against the config_schema from plugin.json.
No external dependencies — simple type + required + default + enum checks.
"""

from __future__ import annotations

from typing import Any

_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_config(
    config: dict[str, Any],
    schema: dict[str, Any],
    plugin_name: str,
) -> tuple[dict[str, Any], list[str]]:
    """Validate plugin config against manifest schema.

    Args:
        config: Raw config dict from config.json plugins section.
        schema: config_schema dict from plugin.json manifest.
        plugin_name: For error messages.

    Returns:
        Tuple of (validated config with defaults applied, list of error strings).
        Empty error list means valid.
    """
    errors: list[str] = []
    result = dict(config)

    for field_name, field_schema in schema.items():
        if not isinstance(field_schema, dict):
            continue

        required = field_schema.get("required", False)
        default = field_schema.get("default")
        field_type = field_schema.get("type", "")
        enum_values = field_schema.get("enum")

        # Apply default if missing
        if field_name not in result:
            if required:
                errors.append(f"{plugin_name}: missing required config '{field_name}'")
                continue
            if default is not None:
                result[field_name] = default
            continue

        value = result[field_name]

        # Bool exclusion for integer type (isinstance(True, int) is True in Python)
        if field_type == "integer" and isinstance(value, bool):
            errors.append(
                f"{plugin_name}: '{field_name}' must be integer, got boolean"
            )
            continue

        # Type check
        expected_type = _TYPE_MAP.get(field_type)
        if expected_type and not isinstance(value, expected_type):
            errors.append(
                f"{plugin_name}: '{field_name}' must be {field_type}, "
                f"got {type(value).__name__}"
            )
            continue

        # Enum check
        if enum_values and value not in enum_values:
            errors.append(
                f"{plugin_name}: '{field_name}' must be one of "
                f"{enum_values}, got '{value}'"
            )

    return result, errors
