"""Tests for plugin manifest loading."""

import json
from pathlib import Path

import pytest

from velo.plugins.manifest import PluginManifest, load_manifest, validate_manifest


@pytest.fixture
def tmp_plugin(tmp_path):
    """Create a minimal plugin directory with __init__.py."""
    plugin_dir = tmp_path / "test-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("def register(ctx): pass\n")
    return plugin_dir


def _write_manifest(plugin_dir: Path, data: dict) -> Path:
    path = plugin_dir / "plugin.json"
    path.write_text(json.dumps(data))
    return path


class TestLoadManifest:
    def test_load_valid_manifest(self, tmp_plugin):
        _write_manifest(
            tmp_plugin,
            {
                "id": "test-plugin",
                "name": "Test Plugin",
                "version": "1.0.0",
                "description": "A test plugin",
                "category": "horizontal",
                "tags": ["test"],
                "config_schema": {},
                "requires": {"channels": [], "env": [], "plugins": []},
                "hooks": [],
                "tools": [],
                "services": False,
                "context_provider": False,
                "used_by_templates": [],
                "ui_hints": {},
            },
        )
        manifest = load_manifest(tmp_plugin)
        assert manifest is not None
        assert manifest.id == "test-plugin"
        assert manifest.version == "1.0.0"

    def test_load_missing_manifest_returns_none(self, tmp_plugin):
        result = load_manifest(tmp_plugin)
        assert result is None

    def test_load_invalid_json_returns_none(self, tmp_plugin):
        (tmp_plugin / "plugin.json").write_text("not json{{{")
        result = load_manifest(tmp_plugin)
        assert result is None

    def test_load_minimal_manifest_with_defaults(self, tmp_plugin):
        _write_manifest(
            tmp_plugin,
            {
                "id": "minimal",
                "name": "Minimal",
                "version": "0.1.0",
                "description": "Minimal plugin",
            },
        )
        manifest = load_manifest(tmp_plugin)
        assert manifest is not None
        assert manifest.category == ""
        assert manifest.tags == []
        assert manifest.config_schema == {}


class TestValidateManifest:
    def test_valid_manifest(self):
        m = PluginManifest(
            id="test",
            name="Test",
            version="1.0.0",
            description="desc",
            category="horizontal",
            tags=[],
            config_schema={},
            requires={"channels": [], "env": [], "plugins": []},
            hooks=[],
            tools=[],
            services=False,
            context_provider=False,
            used_by_templates=[],
            ui_hints={},
        )
        errors = validate_manifest(m)
        assert errors == []

    def test_missing_id(self):
        m = PluginManifest(
            id="",
            name="Test",
            version="1.0.0",
            description="desc",
            category="horizontal",
            tags=[],
            config_schema={},
            requires={},
            hooks=[],
            tools=[],
            services=False,
            context_provider=False,
            used_by_templates=[],
            ui_hints={},
        )
        errors = validate_manifest(m)
        assert any("id" in e for e in errors)

    def test_missing_version(self):
        m = PluginManifest(
            id="test",
            name="Test",
            version="",
            description="desc",
            category="horizontal",
            tags=[],
            config_schema={},
            requires={},
            hooks=[],
            tools=[],
            services=False,
            context_provider=False,
            used_by_templates=[],
            ui_hints={},
        )
        errors = validate_manifest(m)
        assert any("version" in e for e in errors)
