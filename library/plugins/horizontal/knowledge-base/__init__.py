"""Knowledge base plugin — SQLite FTS5 full-text search over local docs and URLs.

All SQLite operations run via run_in_executor to avoid blocking the event loop.
A fresh connection is opened per call (no cross-thread sharing).

Config keys:
    doc_directory (str): Directory to index on startup. Default "".
    extensions (list[str]): File extensions to index. Default [".md", ".txt", ".pdf"].
    chunk_size (int): Characters per chunk. Default 500.
    chunk_overlap (int): Characters of overlap between chunks. Default 50.
    max_documents (int): Maximum documents to index on startup. Default 500.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from velo.agent.tools.base import Tool
from velo.plugins.types import PluginContext

logger = logging.getLogger(__name__)

_CREATE_META = (
    "CREATE TABLE IF NOT EXISTS doc_meta "
    "(path TEXT PRIMARY KEY, mtime REAL, indexed_at TEXT);"
)
_CREATE_FTS = (
    'CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5('
    'path UNINDEXED, chunk_id UNINDEXED, content, tokenize="unicode61");'
)


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection without running DDL."""
    return sqlite3.connect(str(db_path))


def _init_db(db_path: Path) -> None:
    """Create FTS5 tables once. Called from __init__ only."""
    conn = _connect(db_path)
    conn.execute(_CREATE_META)
    conn.execute(_CREATE_FTS)
    conn.commit()
    conn.close()


class _KnowledgeDB:
    """Manages a SQLite FTS5 knowledge base.

    Args:
        db_path: Path to the SQLite database file.
        chunk_size: Characters per chunk.
        chunk_overlap: Overlap characters between adjacent chunks.
    """

    def __init__(self, db_path: Path, chunk_size: int = 500, chunk_overlap: int = 50) -> None:
        self._db_path = db_path
        self._chunk_size = chunk_size
        # Reason: step < chunk_size creates overlap between consecutive chunks
        self._step = max(chunk_size - chunk_overlap, 1)
        _init_db(db_path)  # Create tables once; subsequent _connect() calls skip DDL

    def _chunk(self, text: str) -> list[str]:
        """Split text into overlapping fixed-size chunks."""
        return [
            text[i : i + self._chunk_size]
            for i in range(0, len(text), self._step)
        ]

    def _read_file(self, path: Path) -> str:
        """Read file content; PDF extraction requires pypdf."""
        if path.suffix.lower() == ".pdf":
            try:
                import pypdf  # type: ignore[import-untyped]
                return "\n".join(
                    p.extract_text() or "" for p in pypdf.PdfReader(str(path)).pages
                )
            except ImportError:
                logger.info("knowledge_base.pdf_support_unavailable")
                return ""
        return path.read_text(errors="replace")

    def _upsert_chunks(self, key: str, text: str, mtime: float) -> int:
        """Delete existing chunks for key and insert new ones. Returns chunk count."""
        chunks = self._chunk(text)
        conn = _connect(self._db_path)
        try:
            conn.execute("DELETE FROM docs WHERE path = ?", (key,))
            conn.executemany(
                "INSERT INTO docs(path, chunk_id, content) VALUES (?, ?, ?)",
                [(key, i, c) for i, c in enumerate(chunks)],
            )
            conn.execute(
                "INSERT OR REPLACE INTO doc_meta(path, mtime, indexed_at) VALUES (?, ?, ?)",
                (key, mtime, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            return len(chunks)
        finally:
            conn.close()

    def index_file(self, path: Path) -> int:
        """Index a local file; skips if mtime unchanged. Returns chunk count."""
        mtime = path.stat().st_mtime
        conn = _connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT mtime FROM doc_meta WHERE path = ?", (str(path),)
            ).fetchone()
        finally:
            conn.close()
        if row and abs(row[0] - mtime) < 0.01:
            return 0
        text = self._read_file(path)
        if not text.strip():
            return 0
        count = self._upsert_chunks(str(path), text, mtime)
        logger.info("knowledge_base.file_indexed: %s (%d chunks)", path.name, count)
        return count

    def index_url(self, url: str) -> int:
        """Fetch a URL and index its text content. Returns chunk count."""
        import urllib.request
        with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
            text = resp.read().decode("utf-8", errors="replace")
        if not text.strip():
            return 0
        count = self._upsert_chunks(url, text, time.time())
        logger.info("knowledge_base.url_indexed: %s (%d chunks)", url[:60], count)
        return count

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Full-text search using FTS5 BM25 ranking. Returns list of result dicts."""
        conn = _connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT path, content, rank FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
            return [{"path": r[0], "excerpt": r[1][:200], "rank": r[2]} for r in rows]
        finally:
            conn.close()

    def get_stats(self) -> dict[str, Any]:
        """Return doc_count and last_indexed timestamp."""
        conn = _connect(self._db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM doc_meta").fetchone()[0]
            last = conn.execute("SELECT MAX(indexed_at) FROM doc_meta").fetchone()[0]
            return {"doc_count": count, "last_indexed": last or "never"}
        finally:
            conn.close()


class SearchKnowledgeTool(Tool):
    """Tool: full-text search the knowledge base."""

    def __init__(self, db: _KnowledgeDB) -> None:
        self._db = db

    @property
    def name(self) -> str:
        return "search_knowledge"

    @property
    def description(self) -> str:
        return "Search the indexed knowledge base using full-text search (FTS5 BM25 ranking)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 5, "description": "Max results"},
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Execute full-text search and return formatted results."""
        query = str(kwargs.get("query", ""))
        limit = int(kwargs.get("limit", 5))
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, self._db.search, query, limit)
        if not results:
            return "No results found."
        lines = [f"Found {len(results)} result(s):\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. [{r['path']}]\n   {r['excerpt']}\n")
        return "\n".join(lines)


class AddDocumentTool(Tool):
    """Tool: add a local file or URL to the knowledge base."""

    def __init__(self, db: _KnowledgeDB) -> None:
        self._db = db

    @property
    def name(self) -> str:
        return "add_document"

    @property
    def description(self) -> str:
        return "Add a local file or http(s) URL to the knowledge base for future search."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute file path or http(s):// URL to index",
                }
            },
            "required": ["path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Index a document from a file path or URL and return confirmation."""
        target = str(kwargs.get("path", ""))
        loop = asyncio.get_running_loop()
        if target.startswith("http://") or target.startswith("https://"):
            count = await loop.run_in_executor(None, self._db.index_url, target)
            return f"Indexed URL: {target} ({count} chunks)"
        p = Path(target)
        count = await loop.run_in_executor(None, self._db.index_file, p)
        return f"Indexed file: {p.name} ({count} chunks)"


def setup(ctx: PluginContext) -> None:
    """Plugin entry point — register knowledge base tools, startup indexing, and context.

    Args:
        ctx: Plugin context with config and workspace.
    """
    doc_directory: str = ctx.config.get("doc_directory", "")
    extensions: list[str] = ctx.config.get("extensions", [".md", ".txt", ".pdf"])
    max_documents = int(ctx.config.get("max_documents", 500))

    db = _KnowledgeDB(
        db_path=ctx.workspace / "knowledge_base.db",
        chunk_size=int(ctx.config.get("chunk_size", 500)),
        chunk_overlap=int(ctx.config.get("chunk_overlap", 50)),
    )

    async def on_startup() -> None:
        if not doc_directory:
            return
        doc_dir = Path(doc_directory)
        if not doc_dir.is_dir():
            logger.warning("knowledge_base.doc_dir_not_found: %s", doc_directory)
            return
        loop = asyncio.get_running_loop()
        count = 0
        for path in sorted(doc_dir.rglob("*")):
            if count >= max_documents:
                break
            if path.is_file() and path.suffix.lower() in extensions:
                await loop.run_in_executor(None, db.index_file, path)
                count += 1
        stats = await loop.run_in_executor(None, db.get_stats)
        logger.info("knowledge_base.startup_indexed: %d docs total", stats["doc_count"])

    def context_provider() -> str:
        try:
            return f"Knowledge base: {db.get_stats()['doc_count']} documents indexed"
        except Exception:
            return "Knowledge base: unavailable"

    ctx.on("on_startup", on_startup)
    ctx.register_tool(SearchKnowledgeTool(db))
    ctx.register_tool(AddDocumentTool(db))
    ctx.add_context_provider(context_provider)
    logger.debug("knowledge_base.setup_completed: doc_dir=%s", doc_directory)
