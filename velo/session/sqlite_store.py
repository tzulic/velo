"""SQLite-backed session store for concurrent-safe, structured session persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from velo.session.manager import Session

# SQLite schema — created once on first open.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_consolidated INTEGER DEFAULT 0,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL REFERENCES sessions(key),
    idx INTEGER NOT NULL,
    data TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_key, idx);
"""


class SQLiteSessionStore:
    """SQLite backend for session persistence.

    Uses WAL journal mode and check_same_thread=False to allow concurrent
    readers across async tasks. Sync sqlite3 is intentional — SQLite writes
    are fast enough that briefly holding the event loop is acceptable, and
    aiosqlite adds unnecessary complexity for append-only workloads.
    """

    def __init__(self, path: Path) -> None:
        """Open (or create) the SQLite database at path.

        Args:
            path (Path): Filesystem path to the .db file.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        # Cache of already-persisted message counts per session_key to avoid
        # a COUNT(*) query on every save() call.
        self._persisted_counts: dict[str, int] = {}
        # WAL mode allows concurrent readers while a write is in progress.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def load(self, key: str) -> Session | None:
        """Load a session by key. Returns None if not found.

        Args:
            key (str): Session key (e.g. "telegram:123456").

        Returns:
            Session | None: Loaded session or None.
        """
        from velo.session.manager import Session

        row = self._conn.execute(
            "SELECT created_at, updated_at, last_consolidated, metadata FROM sessions WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None

        created_at_str, updated_at_str, last_consolidated, metadata_json = row
        metadata: dict[str, Any] = json.loads(metadata_json) if metadata_json else {}

        msg_rows = self._conn.execute(
            "SELECT data FROM messages WHERE session_key = ? ORDER BY idx ASC",
            (key,),
        ).fetchall()
        messages = [json.loads(r[0]) for r in msg_rows]

        return Session(
            key=key,
            messages=messages,
            created_at=datetime.fromisoformat(created_at_str),
            updated_at=datetime.fromisoformat(updated_at_str),
            metadata=metadata,
            last_consolidated=last_consolidated,
        )

    def save(self, session: Session) -> None:
        """Upsert session row and append any new messages (append-only).

        Args:
            session (Session): Session to persist.
        """
        # Use cached count to avoid a COUNT(*) query on every save.
        existing = self._persisted_counts.get(session.key, 0)

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO sessions (key, created_at, updated_at, last_consolidated, metadata)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    last_consolidated = excluded.last_consolidated,
                    metadata = excluded.metadata
                """,
                (
                    session.key,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                    session.last_consolidated,
                    json.dumps(session.metadata, ensure_ascii=False) if session.metadata else None,
                ),
            )
            # Append-only: only insert messages beyond what's already stored.
            for idx, msg in enumerate(session.messages[existing:], start=existing):
                self._conn.execute(
                    "INSERT INTO messages (session_key, idx, data) VALUES (?, ?, ?)",
                    (session.key, idx, json.dumps(msg, ensure_ascii=False)),
                )
        self._persisted_counts[session.key] = len(session.messages)

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return metadata dicts for all sessions, sorted by updated_at descending.

        Returns:
            list[dict]: Each dict has key, created_at, updated_at.
        """
        rows = self._conn.execute(
            "SELECT key, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [{"key": r[0], "created_at": r[1], "updated_at": r[2]} for r in rows]

    def migrate_from_jsonl(self, jsonl_path: Path, key: str) -> None:
        """Import an existing JSONL session file into SQLite, then rename it .migrated.

        Args:
            jsonl_path (Path): Path to the JSONL session file.
            key (str): Session key to use in SQLite.
        """
        from velo.session.manager import Session

        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at: datetime | None = None
            last_consolidated = 0

            with open(jsonl_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = (
                            datetime.fromisoformat(data["created_at"])
                            if data.get("created_at")
                            else None
                        )
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            session = Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
            )
            self.save(session)

            # Rename to .migrated so we don't re-migrate on next load.
            migrated_path = jsonl_path.with_suffix(".jsonl.migrated")
            jsonl_path.rename(migrated_path)
            logger.info("session.migrated_to_sqlite: key={}, path={}", key, str(jsonl_path))
        except Exception as e:
            logger.warning("session.migrate_failed: key={}, error={}", key, str(e))

    def close(self) -> None:
        """Close the database connection."""
        try:
            self._conn.close()
        except Exception:
            pass
