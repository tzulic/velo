"""Tests for gateway service management (systemd/launchd)."""

import os
from unittest.mock import patch

from velo.cli.service import (
    _normalize_definition,
    generate_launchd_plist,
    generate_systemd_unit,
    get_service_name,
)


def test_default_service_name():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VELO_HOME", None)
        assert get_service_name() == "velo-gateway"


def test_custom_home_gets_hash_suffix(tmp_path):
    with patch.dict(os.environ, {"VELO_HOME": str(tmp_path)}):
        name = get_service_name()
        assert name.startswith("velo-gateway-")
        assert len(name) == len("velo-gateway-") + 8


def test_systemd_unit_contains_required_sections():
    unit = generate_systemd_unit()
    assert "[Unit]" in unit
    assert "[Service]" in unit
    assert "[Install]" in unit
    assert "Velo AI Assistant" in unit


def test_launchd_plist_valid_xml():
    plist = generate_launchd_plist()
    assert "<?xml" in plist
    assert "ai.velo.gateway" in plist
    assert "gateway" in plist


def test_normalize_strips_trailing_whitespace():
    text = "  line1  \n  line2  \n"
    result = _normalize_definition(text)
    # _normalize_definition strips the whole text first, then rstrips each line
    assert result == "line1\n  line2"
