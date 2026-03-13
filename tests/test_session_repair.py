"""Tests for JSONL session file repair."""

import json
import pytest
from pathlib import Path

from velo.session.manager import Session, SessionManager


def _write_session(path: Path, messages: list, corrupt_line: bool = False) -> None:
    """Helper to write a session JSONL file, optionally with a corrupt line."""
    with open(path, "w", encoding="utf-8") as f:
        meta = {
            "_type": "metadata",
            "key": "test:session",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "metadata": {},
            "last_consolidated": 0,
        }
        f.write(json.dumps(meta) + "\n")
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
        if corrupt_line:
            f.write("this is not valid json {{{\n")


class TestSessionRepair:
    def test_loads_clean_file(self, tmp_path):
        """A clean file should load normally."""
        manager = SessionManager(workspace=tmp_path)
        key = "test:session"
        path = manager._get_session_path(key)
        _write_session(
            path,
            [{"role": "user", "content": "hello"}],
            corrupt_line=False,
        )
        session = manager.get_or_create(key)
        assert len(session.messages) == 1
        assert session.messages[0]["content"] == "hello"

    def test_drops_corrupt_line_and_loads_rest(self, tmp_path):
        """A file with one corrupt line should load the good messages."""
        manager = SessionManager(workspace=tmp_path)
        key = "test:session"
        path = manager._get_session_path(key)
        _write_session(
            path,
            [
                {"role": "user", "content": "msg1"},
                {"role": "assistant", "content": "reply1"},
            ],
            corrupt_line=True,
        )
        session = manager.get_or_create(key)
        assert len(session.messages) == 2
        assert session.messages[0]["content"] == "msg1"

    def test_corrupt_file_creates_backup(self, tmp_path):
        """File repair should create a .bak backup of the original."""
        manager = SessionManager(workspace=tmp_path)
        key = "test:session"
        path = manager._get_session_path(key)
        _write_session(
            path,
            [{"role": "user", "content": "data"}],
            corrupt_line=True,
        )
        manager.get_or_create(key)
        bak_path = path.with_suffix(".bak")
        assert bak_path.exists(), "Backup file should be created on repair"

    def test_repaired_file_is_clean_jsonl(self, tmp_path):
        """After repair, the file should be readable without errors."""
        manager = SessionManager(workspace=tmp_path)
        key = "test:session"
        path = manager._get_session_path(key)
        _write_session(
            path,
            [{"role": "user", "content": "ok"}],
            corrupt_line=True,
        )
        manager.get_or_create(key)

        # Re-read the repaired file
        lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
        for line in lines:
            data = json.loads(line)  # Must not raise
            assert isinstance(data, dict)

    def test_no_backup_on_clean_file(self, tmp_path):
        """No backup should be created when the file is clean."""
        manager = SessionManager(workspace=tmp_path)
        key = "test:session"
        path = manager._get_session_path(key)
        _write_session(
            path,
            [{"role": "user", "content": "clean"}],
            corrupt_line=False,
        )
        manager.get_or_create(key)
        assert not path.with_suffix(".bak").exists()


class TestHeartbeatFields:
    def test_heartbeat_fields_persisted(self, tmp_path):
        """last_heartbeat_text and last_heartbeat_at should survive save/load."""
        from datetime import datetime, timezone

        manager = SessionManager(workspace=tmp_path)
        session = manager.get_or_create("hb:test")
        session.last_heartbeat_text = "Task X completed"
        session.last_heartbeat_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        manager.save(session)

        # Reload
        manager.invalidate("hb:test")
        loaded = manager.get_or_create("hb:test")
        assert loaded.last_heartbeat_text == "Task X completed"
        assert loaded.last_heartbeat_at is not None
        assert loaded.last_heartbeat_at.year == 2026
