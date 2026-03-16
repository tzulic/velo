"""Tests for DM pairing code system."""

from __future__ import annotations

from pathlib import Path

from velo.channels.pairing import PairingManager


class TestPairingManager:
    def test_generate_code_format(self, tmp_path: Path):
        mgr = PairingManager(workspace=tmp_path)
        code = mgr.generate_code()
        assert code.startswith("VELO-")
        assert len(code) == 9  # "VELO-" + 4 chars

    def test_validate_correct_code(self, tmp_path: Path):
        mgr = PairingManager(workspace=tmp_path)
        code = mgr.generate_code()
        assert mgr.validate_code(code, sender_id="user123", channel="telegram")

    def test_code_consumed_after_use(self, tmp_path: Path):
        mgr = PairingManager(workspace=tmp_path)
        code = mgr.generate_code(max_uses=1)
        mgr.validate_code(code, sender_id="user1", channel="telegram")
        assert not mgr.validate_code(code, sender_id="user2", channel="telegram")

    def test_expired_code_rejected(self, tmp_path: Path):
        mgr = PairingManager(workspace=tmp_path)
        code = mgr.generate_code(expires_hours=0)
        assert not mgr.validate_code(code, sender_id="user1", channel="telegram")

    def test_wrong_code_rejected(self, tmp_path: Path):
        mgr = PairingManager(workspace=tmp_path)
        mgr.generate_code()
        assert not mgr.validate_code("VELO-ZZZZ", sender_id="user1", channel="telegram")

    def test_rate_limiting(self, tmp_path: Path):
        mgr = PairingManager(workspace=tmp_path, max_attempts_per_hour=3)
        mgr.generate_code()
        for _ in range(3):
            mgr.validate_code("VELO-XXXX", sender_id="spammer", channel="telegram")
        assert not mgr.validate_code("VELO-XXXX", sender_id="spammer", channel="telegram")

    def test_allowlist_persisted(self, tmp_path: Path):
        mgr = PairingManager(workspace=tmp_path)
        code = mgr.generate_code()
        mgr.validate_code(code, sender_id="user1", channel="telegram")
        assert mgr.is_paired("user1", "telegram")

    def test_code_uniqueness(self, tmp_path: Path):
        mgr = PairingManager(workspace=tmp_path)
        codes = {mgr.generate_code() for _ in range(50)}
        assert len(codes) == 50
