"""Plugin manifest loading and validation.

Reads plugin.json files and parses them into PluginManifest dataclasses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class PluginManifest:
    """Parsed plugin.json manifest."""

    id: str
    name: str
    version: str
    description: str
    category: str = ""
    tags: list[str] = field(default_factory=list)
    config_schema: dict[str, Any] = field(default_factory=dict)
    requires: dict[str, list[str]] = field(default_factory=dict)
    hooks: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    services: bool = False
    context_provider: bool = False
    used_by_templates: list[str] = field(default_factory=list)
    ui_hints: dict[str, str] = field(default_factory=dict)


def load_manifest(plugin_dir: Path) -> PluginManifest | None:
    """Load and parse plugin.json from a plugin directory.

    Args:
        plugin_dir: Path to the plugin directory containing plugin.json.

    Returns:
        PluginManifest if found and valid JSON, None otherwise.
    """
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.is_file():
        return None

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("plugin.manifest_invalid: {} ({})", plugin_dir.name, exc)
        return None

    if not isinstance(raw, dict):
        logger.warning("plugin.manifest_not_dict: {}", plugin_dir.name)
        return None

    return PluginManifest(
        id=raw.get("id", ""),
        name=raw.get("name", ""),
        version=raw.get("version", ""),
        description=raw.get("description", ""),
        category=raw.get("category", ""),
        tags=raw.get("tags", []),
        config_schema=raw.get("config_schema", {}),
        requires=raw.get("requires", {}),
        hooks=raw.get("hooks", []),
        tools=raw.get("tools", []),
        services=raw.get("services", False),
        context_provider=raw.get("context_provider", False),
        used_by_templates=raw.get("used_by_templates", []),
        ui_hints=raw.get("ui_hints", {}),
    )


def validate_manifest(manifest: PluginManifest) -> list[str]:
    """Validate a parsed manifest for required fields.

    Args:
        manifest: The parsed manifest to validate.

    Returns:
        List of error strings. Empty list means valid.
    """
    errors: list[str] = []
    if not manifest.id:
        errors.append("manifest missing required field 'id'")
    if not manifest.version:
        errors.append("manifest missing required field 'version'")
    if not manifest.name:
        errors.append("manifest missing required field 'name'")
    if not manifest.description:
        errors.append("manifest missing required field 'description'")
    return errors
