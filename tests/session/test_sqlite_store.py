"""Tests for SQLiteSessionStore."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from velo.session.manager import Session
from velo.session.sqlite_store import SQLiteSessionStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteSessionStore:
    """Provide a fresh SQLiteSessionStore backed by a temp file."""
    return SQLiteSessionStore(tmp_path / "sessions.db")


def _make_session(key: str = "test:user", n_messages: int = 2) -> Session:
    """Create a simple test session with n_messages."""
    s = Session(key=key)
    for i in range(n_messages):
        role = "user" if i % 2 == 0 else "assistant"
        s.add_message(role, f"Message {i}")
    return s


class TestSQLiteSessionStoreCRUD:
    """Basic create/read/update tests."""

    def test_save_and_load_roundtrip(self, store: SQLiteSessionStore) -> None:
        """Saved session can be loaded back with all messages intact."""
        session = _make_session("telegram:42", n_messages=3)
        store.save(session)

        loaded = store.load("telegram:42")
        assert loaded is not None
        assert loaded.key == "telegram:42"
        assert len(loaded.messages) == 3
        assert loaded.messages[0]["content"] == "Message 0"

    def test_load_missing_key_returns_none(self, store: SQLiteSessionStore) -> None:
        """Loading a non-existent key returns None."""
        assert store.load("nonexistent:key") is None

    def test_save_updates_last_consolidated(self, store: SQLiteSessionStore) -> None:
        """last_consolidated field is persisted and restored."""
        session = _make_session()
        session.last_consolidated = 2
        store.save(session)

        loaded = store.load(session.key)
        assert loaded is not None
        assert loaded.last_consolidated == 2

    def test_list_sessions_returns_saved(self, store: SQLiteSessionStore) -> None:
        """list_sessions includes all saved sessions."""
        store.save(_make_session("ch:1"))
        store.save(_make_session("ch:2"))

        items = store.list_sessions()
        keys = {i["key"] for i in items}
        assert "ch:1" in keys
        assert "ch:2" in keys


class TestSQLiteSessionStoreAppendOnly:
    """Append-only semantics: re-saving does not duplicate messages."""

    def test_resave_does_not_duplicate_messages(self, store: SQLiteSessionStore) -> None:
        """Saving the same session twice doesn't double the messages."""
        session = _make_session(n_messages=2)
        store.save(session)
        store.save(session)  # identical save

        loaded = store.load(session.key)
        assert loaded is not None
        assert len(loaded.messages) == 2

    def test_incremental_append(self, store: SQLiteSessionStore) -> None:
        """New messages added after first save are appended correctly."""
        session = _make_session(n_messages=2)
        store.save(session)

        session.add_message("user", "Third message")
        store.save(session)

        loaded = store.load(session.key)
        assert loaded is not None
        assert len(loaded.messages) == 3
        assert loaded.messages[2]["content"] == "Third message"


class TestSQLiteSessionStoreMigration:
    """JSONL → SQLite migration."""

    def test_migrate_from_jsonl(self, store: SQLiteSessionStore, tmp_path: Path) -> None:
        """migrate_from_jsonl imports messages from JSONL and renames the source file."""
        jsonl_path = tmp_path / "cli_direct.jsonl"

        # Write a minimal JSONL session file.
        metadata = {
            "_type": "metadata",
            "key": "cli:direct",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "last_consolidated": 0,
            "metadata": {},
        }
        msg1 = {"role": "user", "content": "Hello"}
        msg2 = {"role": "assistant", "content": "Hi"}

        with open(jsonl_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(metadata) + "\n")
            f.write(json.dumps(msg1) + "\n")
            f.write(json.dumps(msg2) + "\n")

        store.migrate_from_jsonl(jsonl_path, "cli:direct")

        # Original file renamed to .migrated
        migrated = tmp_path / "cli_direct.jsonl.migrated"
        assert migrated.exists()
        assert not jsonl_path.exists()

        # Messages imported into SQLite
        loaded = store.load("cli:direct")
        assert loaded is not None
        assert len(loaded.messages) == 2
        assert loaded.messages[0]["content"] == "Hello"

    def test_migrate_handles_missing_file_gracefully(
        self, store: SQLiteSessionStore, tmp_path: Path
    ) -> None:
        """migrate_from_jsonl does not crash when file doesn't exist."""
        missing = tmp_path / "ghost.jsonl"
        store.migrate_from_jsonl(missing, "ghost:session")  # should not raise
        assert store.load("ghost:session") is None
