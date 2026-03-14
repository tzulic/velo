"""Session management for conversation history."""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from velo.config.paths import get_legacy_sessions_dir
from velo.utils.helpers import ensure_dir, safe_filename


@dataclass
class Session:
    """
    A conversation session.

    Stores messages in JSONL format for easy reading and persistence.

    Important: Messages are append-only for LLM cache efficiency.
    The consolidation process writes summaries to MEMORY.md/HISTORY.md
    but does NOT modify the messages list or get_history() output.
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files
    # Heartbeat deduplication: track last delivered heartbeat text and time
    last_heartbeat_text: str | None = None
    last_heartbeat_at: datetime | None = None
    parent_session_id: str | None = None

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {"role": role, "content": content, "timestamp": datetime.now().isoformat(), **kwargs}
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Return unconsolidated messages for LLM input, aligned to a user turn."""
        unconsolidated = self.messages[self.last_consolidated :]
        sliced = unconsolidated[-max_messages:]

        # Drop leading non-user messages to avoid orphaned tool_result blocks
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                break

        out: list[dict[str, Any]] = []
        for m in sliced:
            entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored as JSONL files by default (backend="jsonl") or in a
    SQLite database (backend="sqlite") for concurrent-safe, structured access.
    """

    def __init__(self, workspace: Path, backend: Literal["jsonl", "sqlite"] = "jsonl") -> None:
        """Initialize the session manager.

        Args:
            workspace (Path): Workspace directory where sessions are stored.
            backend (Literal["jsonl", "sqlite"]): Storage backend. Defaults to "jsonl".
        """
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self.legacy_sessions_dir = get_legacy_sessions_dir()
        self._cache: dict[str, Session] = {}
        self._backend = backend
        self._sqlite: Any = None  # SQLiteSessionStore, lazily imported
        if backend == "sqlite":
            from velo.session.sqlite_store import SQLiteSessionStore

            db_path = self.sessions_dir / "sessions.db"
            self._sqlite = SQLiteSessionStore(db_path)

    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        """Legacy global session path (~/.velo/sessions/)."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session from the configured backend."""
        if self._sqlite is not None:
            return self._load_sqlite(key)
        return self._load_jsonl(key)

    def _load_sqlite(self, key: str) -> Session | None:
        """Load a session from SQLite, migrating from JSONL if needed."""
        # Migrate JSONL → SQLite on first access.
        jsonl_path = self._get_session_path(key)
        if jsonl_path.exists():
            self._sqlite.migrate_from_jsonl(jsonl_path, key)
        return self._sqlite.load(key)

    def _load_jsonl(self, key: str) -> Session | None:
        """Load a session from a JSONL file."""
        path = self._get_session_path(key)
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                try:
                    shutil.move(str(legacy_path), str(path))
                    logger.info("Migrated session {} from legacy path", key)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)

        if not path.exists():
            return None

        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at = None
            last_consolidated = 0
            last_heartbeat_text: str | None = None
            last_heartbeat_at: datetime | None = None
            dropped = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        dropped += 1
                        continue

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = (
                            datetime.fromisoformat(data["created_at"])
                            if data.get("created_at")
                            else None
                        )
                        last_consolidated = data.get("last_consolidated", 0)
                        last_heartbeat_text = data.get("last_heartbeat_text")
                        _lha = data.get("last_heartbeat_at")
                        last_heartbeat_at = datetime.fromisoformat(_lha) if _lha else None
                    else:
                        messages.append(data)

            session = Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
                last_heartbeat_text=last_heartbeat_text,
                last_heartbeat_at=last_heartbeat_at,
            )

            # Repair: if corrupt lines were found, back up and rewrite clean data
            if dropped > 0:
                logger.warning("session.repair: dropped {} corrupt lines from {}", dropped, key)
                shutil.copy2(path, path.with_suffix(".bak"))
                self._save_jsonl(session)

            return session
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            return None

    def save(self, session: Session) -> None:
        """Save a session to the configured backend."""
        if self._sqlite is not None:
            self._sqlite.save(session)
        else:
            self._save_jsonl(session)
        self._cache[session.key] = session

    def _save_jsonl(self, session: Session) -> None:
        """Persist a session to a JSONL file."""
        path = self._get_session_path(session.key)

        with open(path, "w", encoding="utf-8") as f:
            metadata_line: dict[str, Any] = {
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated,
            }
            if session.last_heartbeat_text is not None:
                metadata_line["last_heartbeat_text"] = session.last_heartbeat_text
            if session.last_heartbeat_at is not None:
                metadata_line["last_heartbeat_at"] = session.last_heartbeat_at.isoformat()
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions sorted by most recently updated.

        Returns:
            List of session info dicts with key, created_at, updated_at.
        """
        if self._sqlite is not None:
            return self._sqlite.list_sessions()

        sessions = []
        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                # Read just the metadata line
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            key = data.get("key") or path.stem.replace("_", ":", 1)
                            sessions.append(
                                {
                                    "key": key,
                                    "created_at": data.get("created_at"),
                                    "updated_at": data.get("updated_at"),
                                    "path": str(path),
                                }
                            )
            except Exception:
                continue

        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
