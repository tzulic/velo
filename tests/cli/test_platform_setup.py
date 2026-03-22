"""Tests for the platform setup wizard PLATFORMS registry."""

import json

from velo.cli.platform_setup import PLATFORMS, apply_platform_values
from velo.config.loader import load_config


def test_platforms_registry_has_core_platforms():
    """All five supported platforms are present in the registry."""
    names = [p["key"] for p in PLATFORMS]
    assert "telegram" in names
    assert "discord" in names
    assert "slack" in names
    assert "whatsapp" in names
    assert "matrix" in names


def test_each_platform_has_required_fields():
    """Every platform entry has the required top-level fields and var fields."""
    for p in PLATFORMS:
        assert "key" in p, f"Missing 'key' in platform: {p}"
        assert "label" in p, f"Missing 'label' in {p['key']}"
        assert "emoji" in p, f"Missing 'emoji' in {p['key']}"
        assert "vars" in p, f"Missing 'vars' in {p['key']}"
        assert "setup_instructions" in p, f"Missing 'setup_instructions' in {p['key']}"
        assert len(p["setup_instructions"]) > 0, f"Empty setup_instructions in {p['key']}"
        for v in p["vars"]:
            assert "attr_path" in v, f"Missing attr_path in {p['key']}.{v.get('name', '?')}"
            assert "name" in v, f"Missing name in {p['key']} var"
            assert "prompt" in v, f"Missing prompt in {p['key']} var"


def test_no_signal_platform():
    """Signal has no ChannelsConfig entry -- must not be in wizard."""
    names = [p["key"] for p in PLATFORMS]
    assert "signal" not in names


def test_platform_count():
    """Exactly five platforms in the registry."""
    assert len(PLATFORMS) == 5


def test_attr_paths_start_with_channels():
    """All attr_path values must start with 'channels.<key>.' for config resolution."""
    for p in PLATFORMS:
        for v in p["vars"]:
            assert v["attr_path"].startswith(f"channels.{p['key']}."), (
                f"attr_path '{v['attr_path']}' does not start with 'channels.{p['key']}.' "
                f"in platform {p['key']}"
            )


def test_password_fields_are_tokens():
    """Fields marked password=True should be token/secret fields."""
    for p in PLATFORMS:
        for v in p["vars"]:
            if v.get("password"):
                lower_name = v["name"].lower()
                assert any(kw in lower_name for kw in ("token", "secret", "key", "password")), (
                    f"password=True on non-secret field '{v['name']}' in {p['key']}"
                )


def test_allowlist_fields_have_is_allowlist():
    """Fields for allow_from should be marked is_allowlist=True."""
    for p in PLATFORMS:
        for v in p["vars"]:
            if "allow_from" in v["attr_path"]:
                assert v.get("is_allowlist") is True, (
                    f"allow_from field '{v['name']}' in {p['key']} missing is_allowlist=True"
                )


# ── apply_platform_values tests ──────────────────────────────────────


def test_apply_platform_values_writes_to_config(tmp_path):
    """Applying a channel token writes it and auto-enables the channel."""
    config_path = tmp_path / "config.json"
    config_path.write_text("{}")

    values = {"channels.telegram.token": "123:ABC"}
    apply_platform_values(values, config_path)

    config = load_config(config_path)
    assert config.channels.telegram.token == "123:ABC"
    assert config.channels.telegram.enabled is True  # auto-enabled


def test_apply_preserves_existing_values(tmp_path):
    """Applying new channel values must not clobber unrelated config sections."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"agents": {"defaults": {"model": "custom/model"}}}))

    values = {"channels.discord.token": "my-token"}
    apply_platform_values(values, config_path)

    config = load_config(config_path)
    assert config.channels.discord.token == "my-token"
    assert config.agents.defaults.model == "custom/model"  # preserved


def test_apply_allowlist_sets_list(tmp_path):
    """Allowlist values (lists) are stored as lists on the Pydantic model."""
    config_path = tmp_path / "config.json"
    config_path.write_text("{}")

    values = {"channels.telegram.allow_from": ["user1", "user2"]}
    apply_platform_values(values, config_path)

    config = load_config(config_path)
    assert config.channels.telegram.allow_from == ["user1", "user2"]


def test_apply_multiple_values_at_once(tmp_path):
    """Multiple dot-path keys in a single call are all applied."""
    config_path = tmp_path / "config.json"
    config_path.write_text("{}")

    values = {
        "channels.slack.bot_token": "xoxb-123",
        "channels.slack.app_token": "xapp-456",
    }
    apply_platform_values(values, config_path)

    config = load_config(config_path)
    assert config.channels.slack.bot_token == "xoxb-123"
    assert config.channels.slack.app_token == "xapp-456"
    assert config.channels.slack.enabled is True


def test_apply_does_not_enable_when_no_credential(tmp_path):
    """Setting only an allowlist (no token/secret) should not auto-enable."""
    config_path = tmp_path / "config.json"
    config_path.write_text("{}")

    values = {"channels.telegram.allow_from": ["user1"]}
    apply_platform_values(values, config_path)

    config = load_config(config_path)
    assert config.channels.telegram.enabled is False


def test_apply_saved_file_uses_camel_case(tmp_path):
    """The persisted JSON must use camelCase keys (via Pydantic aliases)."""
    config_path = tmp_path / "config.json"
    config_path.write_text("{}")

    values = {"channels.slack.bot_token": "xoxb-test"}
    apply_platform_values(values, config_path)

    raw = json.loads(config_path.read_text())
    slack_cfg = raw["channels"]["slack"]
    # save_config uses by_alias=True, so keys must be camelCase
    assert "botToken" in slack_cfg
    assert "bot_token" not in slack_cfg
