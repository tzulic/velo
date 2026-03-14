"""SQLite-backed session store for concurrent-safe, structured session persistence."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

# Pre-compiled FTS5 sanitization patterns
_RE_FTS_SPECIAL = re.compile(r"[+{}()]")
_RE_LEADING_WILDCARD = re.compile(r"^\*+")
_RE_SPACE_WILDCARD = re.compile(r"\s\*+")
_RE_AND = re.compile(r"\bAND\b")
_RE_OR = re.compile(r"\bOR\b")
_RE_NOT = re.compile(r"\bNOT\b")
_RE_WHITESPACE = re.compile(r"\s+")
_RE_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]")

if TYPE_CHECKING:
    from velo.session.manager import Session

# SQLite schema — created once on first open.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_consolidated INTEGER DEFAULT 0,
    metadata TEXT,
    parent_session_id TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL REFERENCES sessions(key),
    idx INTEGER NOT NULL,
    data TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_key, idx);
-- FTS5 full-text search on messages (created separately for graceful fallback)
"""


def _extract_indexable_content(msg: dict[str, Any]) -> str | None:
    """Extract text content from a message if it should be indexed.

    Only user and assistant messages with non-empty content are indexable.

    Args:
        msg: A message dict with at least 'role' and 'content' keys.

    Returns:
        str | None: Text content to index, or None if not indexable.
    """
    role = msg.get("role", "")
    if role not in ("user", "assistant") or not msg.get("content"):
        return None
    content = msg["content"]
    return content if isinstance(content, str) else str(content)


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
        # Migration: add parent_session_id column if missing (existing DBs).
        try:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN parent_session_id TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        self._conn.commit()

        # FTS5 full-text search table (graceful fallback if FTS5 not available)
        self._fts5_available = True
        try:
            self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content, session_key UNINDEXED, created_at UNINDEXED,
                    tokenize='porter ascii'
                )
            """)
            self._conn.commit()
        except sqlite3.OperationalError:
            self._fts5_available = False
            # Fallback: plain table with LIKE queries
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS messages_fts_plain (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT,
                    session_key TEXT,
                    created_at TEXT
                )
            """)
            self._conn.commit()

        self._fts_indexed = False

    def load(self, key: str) -> Session | None:
        """Load a session by key. Returns None if not found.

        Args:
            key (str): Session key (e.g. "telegram:123456").

        Returns:
            Session | None: Loaded session or None.
        """
        from velo.session.manager import Session

        row = self._conn.execute(
            "SELECT created_at, updated_at, last_consolidated, metadata, parent_session_id"
            " FROM sessions WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None

        created_at_str, updated_at_str, last_consolidated, metadata_json, parent_session_id = row
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
            parent_session_id=parent_session_id,
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
                INSERT INTO sessions (key, created_at, updated_at, last_consolidated, metadata,
                                      parent_session_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    last_consolidated = excluded.last_consolidated,
                    metadata = excluded.metadata,
                    parent_session_id = excluded.parent_session_id
                """,
                (
                    session.key,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                    session.last_consolidated,
                    json.dumps(session.metadata, ensure_ascii=False) if session.metadata else None,
                    session.parent_session_id,
                ),
            )
            # Append-only: only insert messages beyond what's already stored.
            for idx, msg in enumerate(session.messages[existing:], start=existing):
                self._conn.execute(
                    "INSERT INTO messages (session_key, idx, data) VALUES (?, ?, ?)",
                    (session.key, idx, json.dumps(msg, ensure_ascii=False)),
                )
                # Index new messages for full-text search
                content_text = _extract_indexable_content(msg)
                if content_text:
                    self.index_message(
                        session.key,
                        content_text,
                        msg.get("timestamp", session.updated_at.isoformat()),
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

    def index_message(self, session_key: str, content: str, created_at: str) -> None:
        """Index a message for full-text search.

        Args:
            session_key: Session key (e.g. "telegram:123").
            content: Message text content.
            created_at: ISO timestamp string.
        """
        if self._fts5_available:
            self._conn.execute(
                "INSERT INTO messages_fts (content, session_key, created_at) VALUES (?, ?, ?)",
                (content, session_key, created_at),
            )
        else:
            self._conn.execute(
                "INSERT INTO messages_fts_plain (content, session_key, created_at) VALUES (?, ?, ?)",
                (content, session_key, created_at),
            )

    def search_messages(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Search messages using FTS5 with BM25 ranking.

        Args:
            query: Search keywords.
            max_results: Maximum results to return.

        Returns:
            List of dicts with session_key, content (truncated to 500 chars),
            created_at, and score.
        """
        self._ensure_fts_index()
        sanitized = self._sanitize_fts5_query(query)
        if not sanitized.strip():
            return []

        results: list[dict[str, Any]] = []

        if self._fts5_available:
            try:
                rows = self._conn.execute(
                    """
                    SELECT session_key, content, created_at, bm25(messages_fts)
                    FROM messages_fts
                    WHERE messages_fts MATCH ?
                    ORDER BY bm25(messages_fts) ASC
                    LIMIT ?
                    """,
                    (sanitized, max_results),
                ).fetchall()
                for row in rows:
                    results.append(
                        {
                            "session_key": row[0],
                            "content": row[1][:500],
                            "created_at": row[2],
                            "score": row[3],
                        }
                    )
            except sqlite3.OperationalError as e:
                logger.warning("session.fts_search_failed: error={}", str(e))
                return []
        else:
            # Fallback: LIKE-based search
            like_pattern = f"%{sanitized}%"
            rows = self._conn.execute(
                """
                SELECT session_key, content, created_at
                FROM messages_fts_plain
                WHERE content LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (like_pattern, max_results),
            ).fetchall()
            for row in rows:
                results.append(
                    {
                        "session_key": row[0],
                        "content": row[1][:500],
                        "created_at": row[2],
                        "score": 0.0,
                    }
                )

        return results

    @staticmethod
    def _sanitize_fts5_query(query: str) -> str:
        """Strip FTS5 operators that could crash the query.

        Removes: +, *, {}, (), AND, OR, NOT as standalone operators.
        Handles: unclosed quotes, leading wildcards.

        Args:
            query: Raw user query string.

        Returns:
            Cleaned query safe for FTS5 MATCH.
        """
        # Strip special FTS5 characters
        cleaned = _RE_FTS_SPECIAL.sub(" ", query)
        # Remove leading wildcards
        cleaned = _RE_LEADING_WILDCARD.sub("", cleaned)
        cleaned = _RE_SPACE_WILDCARD.sub(" ", cleaned)
        # Balance unclosed quotes
        if cleaned.count('"') % 2 != 0:
            cleaned += '"'
        # Remove standalone FTS5 boolean operators
        cleaned = _RE_AND.sub(" ", cleaned)
        cleaned = _RE_OR.sub(" ", cleaned)
        cleaned = _RE_NOT.sub(" ", cleaned)
        # Collapse whitespace
        cleaned = _RE_WHITESPACE.sub(" ", cleaned).strip()
        # Fallback: if empty after sanitization, use first word of original
        if not cleaned:
            first_word = _RE_NON_ALNUM.sub("", query.split()[0] if query.split() else "")
            return first_word
        return cleaned

    def _ensure_fts_index(self) -> None:
        """Lazily backfill FTS index from existing messages on first search."""
        if self._fts_indexed:
            return

        # Check if FTS table already has rows
        table = "messages_fts" if self._fts5_available else "messages_fts_plain"
        count = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
        if count > 0:
            self._fts_indexed = True
            return

        # Backfill from messages table in batches to avoid loading all into memory
        cursor = self._conn.execute(
            "SELECT session_key, data FROM messages ORDER BY id ASC"
        )
        indexed = 0
        while True:
            batch = cursor.fetchmany(500)
            if not batch:
                break
            for session_key, data_json in batch:
                try:
                    msg = json.loads(data_json)
                except (json.JSONDecodeError, TypeError):
                    continue
                content_text = _extract_indexable_content(msg)
                if content_text:
                    timestamp = msg.get("timestamp", "")
                    self.index_message(session_key, content_text, timestamp)
                    indexed += 1

        self._conn.commit()
        self._fts_indexed = True
        logger.debug("session.fts_backfill_completed: indexed={}", indexed)

    def close(self) -> None:
        """Close the database connection."""
        try:
            self._conn.close()
        except Exception:
            pass
