"""BM25 history search using SQLite FTS5 (with LIKE fallback)."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class HistoryEntry:
    """A single result from the history index.

    Attributes:
        rowid (int): SQLite row identifier.
        content (str): Text content of the entry.
        created_at (datetime | None): Approximate date of the entry.
        score (float): Relevance score (higher = more relevant, with temporal decay).
    """

    rowid: int
    content: str
    created_at: datetime | None
    score: float


class HistoryIndex:
    """BM25 history search backed by SQLite FTS5 (or LIKE if FTS5 unavailable).

    Parses HISTORY.md from the workspace, splits it into sections, and indexes
    them for fast full-text retrieval with temporal decay scoring.

    Args:
        workspace (Path): Workspace directory containing memory/HISTORY.md.
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.db_path = workspace / ".velo" / "history_index.db"
        self._fts5_available: bool | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection, creating parent dirs if needed."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self.db_path))

    def _check_fts5(self, conn: sqlite3.Connection) -> bool:
        """Check whether FTS5 is compiled into this SQLite build.

        Args:
            conn (sqlite3.Connection): Open database connection.

        Returns:
            bool: True if FTS5 is available.
        """
        if self._fts5_available is not None:
            return self._fts5_available
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA compile_options")
            options = {row[0] for row in cur.fetchall()}
            self._fts5_available = "ENABLE_FTS5" in options
        except Exception:
            self._fts5_available = False
        if not self._fts5_available:
            logger.warning("history_index.fts5_unavailable: falling back to LIKE search")
        return self._fts5_available  # type: ignore[return-value]

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        """Create FTS5 virtual table (or plain table as fallback).

        Args:
            conn (sqlite3.Connection): Open database connection.
        """
        cur = conn.cursor()
        if self._check_fts5(conn):
            cur.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(
                    content,
                    created_at UNINDEXED,
                    tokenize='porter ascii'
                )
                """
            )
        else:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS history_plain (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT,
                    created_at TEXT
                )
                """
            )
        conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Parse HISTORY.md and populate the FTS5 (or plain) index.

        Looks for memory/HISTORY.md first, then HISTORY.md at workspace root.
        Rebuilds from scratch on every call.
        """
        history_file = self.workspace / "memory" / "HISTORY.md"
        if not history_file.exists():
            history_file = self.workspace / "HISTORY.md"
        if not history_file.exists():
            logger.debug("history_index.build_skipped: no HISTORY.md found")
            return

        try:
            content = history_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("history_index.build_failed: {}", e)
            return

        entries = _parse_history_entries(content)
        if not entries:
            return

        conn = self._connect()
        try:
            self._init_schema(conn)  # sets self._fts5_available
            cur = conn.cursor()
            rows = [(e["content"], e.get("date")) for e in entries]
            if self._fts5_available:
                cur.execute("DELETE FROM history_fts")
                cur.executemany("INSERT INTO history_fts(content, created_at) VALUES (?, ?)", rows)
            else:
                cur.execute("DELETE FROM history_plain")
                cur.executemany(
                    "INSERT INTO history_plain(content, created_at) VALUES (?, ?)", rows
                )
            conn.commit()
            logger.info("history_index.built: {} entries indexed", len(entries))
        finally:
            conn.close()

    def search(self, query: str, max_results: int = 10) -> list[HistoryEntry]:
        """Search history with BM25 scoring and temporal decay.

        Args:
            query (str): Search terms.
            max_results (int): Maximum number of results to return.

        Returns:
            list[HistoryEntry]: Matching entries, best matches first.
        """
        conn = self._connect()
        try:
            self._init_schema(conn)
            cur = conn.cursor()
            now = datetime.now(timezone.utc)
            results: list[HistoryEntry] = []

            if self._check_fts5(conn):
                try:
                    cur.execute(
                        """
                        SELECT rowid, content, created_at, bm25(history_fts) AS score
                        FROM history_fts
                        WHERE history_fts MATCH ?
                        ORDER BY score
                        LIMIT ?
                        """,
                        (query, max_results * 2),
                    )
                    for rowid, content, created_at_str, score in cur.fetchall():
                        decay = _temporal_decay(created_at_str, now)
                        results.append(
                            HistoryEntry(
                                rowid=rowid,
                                content=content,
                                created_at=_parse_date(created_at_str),
                                # bm25() returns negative values (lower = better match)
                                score=float(score) * decay,
                            )
                        )
                    # Sort ascending (most negative = best match)
                    results.sort(key=lambda e: e.score)
                    return results[:max_results]
                except sqlite3.OperationalError:
                    # Table may be empty or query syntax error; fall through
                    pass

            # LIKE fallback
            like_query = f"%{query}%"
            cur.execute(
                "SELECT id, content, created_at FROM history_plain WHERE content LIKE ? LIMIT ?",
                (like_query, max_results),
            )
            for rowid, content, created_at_str in cur.fetchall():
                decay = _temporal_decay(created_at_str, now)
                results.append(
                    HistoryEntry(
                        rowid=rowid,
                        content=content,
                        created_at=_parse_date(created_at_str),
                        score=1.0 * decay,
                    )
                )
            return results
        finally:
            conn.close()


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _parse_history_entries(content: str) -> list[dict[str, Any]]:
    """Split HISTORY.md into searchable sections.

    Args:
        content (str): Full text of HISTORY.md.

    Returns:
        list[dict]: Each dict has 'content' (str) and optional 'date' (str | None).
    """
    entries: list[dict[str, Any]] = []
    # Split on markdown headings (## or #)
    sections = re.split(r"\n(?=##? )", content)
    for section in sections:
        section = section.strip()
        if not section:
            continue
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", section[:120])
        date_str = date_match.group(0) if date_match else None
        entries.append({"content": section, "date": date_str})
    return entries


def _temporal_decay(date_str: str | None, now: datetime) -> float:
    """Calculate temporal decay: 1.0 / (1.0 + days_old * 0.01).

    Args:
        date_str (str | None): ISO date string or YYYY-MM-DD.
        now (datetime): Current UTC time.

    Returns:
        float: Decay factor in (0, 1]. Recent entries score higher.
    """
    if not date_str:
        return 1.0
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days_old = max(0, (now - dt).days)
        return 1.0 / (1.0 + days_old * 0.01)
    except Exception:
        return 1.0


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse a date string into a datetime object.

    Args:
        date_str (str | None): ISO format or YYYY-MM-DD string.

    Returns:
        datetime | None: Parsed datetime, or None on failure.
    """
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return None
