"""Tests for the platform setup wizard PLATFORMS registry."""

from velo.cli.platform_setup import PLATFORMS


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
                assert any(
                    kw in lower_name for kw in ("token", "secret", "key", "password")
                ), f"password=True on non-secret field '{v['name']}' in {p['key']}"


def test_allowlist_fields_have_is_allowlist():
    """Fields for allow_from should be marked is_allowlist=True."""
    for p in PLATFORMS:
        for v in p["vars"]:
            if "allow_from" in v["attr_path"]:
                assert v.get("is_allowlist") is True, (
                    f"allow_from field '{v['name']}' in {p['key']} missing is_allowlist=True"
                )
