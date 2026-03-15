"""Honcho adapter: bridge between Velo sessions and the Honcho SDK.

Handles session lifecycle, message sync, context prefetch, and
dialectic queries. All public methods degrade gracefully — SDK errors
are logged but never raised to the caller.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from velo.agent.honcho.config import HonchoConfig


@dataclass
class HonchoSessionState:
    """Tracks per-session Honcho objects and sync progress.

    Args:
        session_key: Velo session key (e.g. "telegram:12345").
        user_peer: Honcho Peer for the human user.
        ai_peer: Honcho Peer for the AI assistant.
        session: Honcho Session object.
        last_synced_idx: Index of last message synced to Honcho.
        context_cache: Prefetched context string for next turn.
    """

    session_key: str
    user_peer: Any = None
    ai_peer: Any = None
    session: Any = None
    last_synced_idx: int = 0
    context_cache: str = ""
    _prefetch_task: asyncio.Task[None] | None = field(default=None, repr=False)


class HonchoAdapter:
    """Core bridge between Velo sessions and Honcho SDK.

    Uses Honcho sync client with .aio accessor for async operations.
    All public methods catch exceptions and return empty/False so the
    agent loop is never disrupted by Honcho failures.

    Args:
        config: Honcho configuration.
    """

    # Honcho batch limit for add_messages
    _MAX_BATCH_SIZE = 100

    def __init__(self, config: HonchoConfig) -> None:
        self._config = config
        self._client: Any = None
        self._aio: Any = None  # Honcho async accessor (client.aio)
        self._sessions: dict[str, HonchoSessionState] = {}
        self._lock = asyncio.Lock()
        self._current_session_key: str = ""
        self._background_tasks: set[asyncio.Task[None]] = set()

    @property
    def current_session_key(self) -> str:
        """The session key currently being processed by the agent loop.

        Set by the loop before each turn so tools can access it.
        """
        return self._current_session_key

    def set_current_session(self, key: str) -> None:
        """Set the active session key for tool calls.

        Called by AgentLoop before _run_agent_loop() so Honcho tools
        know which session to operate on.

        Args:
            key: Velo session key (e.g. "telegram:12345").
        """
        self._current_session_key = key

    def track_task(self, key: str, task: asyncio.Task[None]) -> None:
        """Track a background task so it can be awaited on shutdown.

        Tasks auto-remove themselves when done via a callback.

        Args:
            key: Session key (for logging on failure).
            task: The asyncio task to track.
        """
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def get_prefetched_context(self) -> str:
        """Get and clear prefetched context for the current session.

        Convenience wrapper that combines current_session_key with
        pop_context_result. Returns "" on cold start or if no session.

        Returns:
            Cached user context string, or "".
        """
        return self.pop_context_result(self._current_session_key)

    def _ensure_client(self) -> Any:
        """Lazily create the Honcho client and its async accessor.

        Returns:
            The Honcho .aio async accessor.
        """
        if self._aio is None:
            try:
                from honcho import Honcho

                self._client = Honcho(
                    api_key=self._config.api_key,
                    workspace_id=self._config.workspace_id,
                    base_url=self._config.api_base,
                )
                self._aio = self._client.aio
                logger.info(
                    "honcho.client_created: workspace={}",
                    self._config.workspace_id,
                )
            except ImportError:
                logger.error(
                    "honcho.import_failed: honcho-ai package not installed"
                )
                raise
        return self._aio

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def get_or_create(self, key: str) -> HonchoSessionState:
        """Get or create a Honcho session state for the given Velo session key.

        Creates peer and session objects via the Honcho API (get-or-create
        semantics on the server side).

        Args:
            key: Velo session key (e.g. "telegram:12345").

        Returns:
            HonchoSessionState with peer and session objects.
        """
        if key in self._sessions:
            return self._sessions[key]

        async with self._lock:
            # Double-check after acquiring lock
            if key in self._sessions:
                return self._sessions[key]

            try:
                aio = self._ensure_client()

                # Reason: peer() and session() are async get-or-create calls.
                # They create the resource on first call, return existing on subsequent.
                user_peer = await aio.peer("user")
                ai_peer = await aio.peer(self._config.ai_peer)
                # Reason: Honcho session IDs only allow [a-zA-Z0-9_-].
                # Velo keys use colons (e.g. "telegram:12345"), so sanitize.
                import re
                honcho_id = re.sub(r"[^a-zA-Z0-9_-]", "-", key)
                # Reason: passing metadata={} forces the SDK to make a server-side
                # get-or-create call. Without it, session() only creates a local
                # object and add_messages later fails with 500.
                session = await aio.session(honcho_id, metadata={})

                state = HonchoSessionState(
                    session_key=key,
                    user_peer=user_peer,
                    ai_peer=ai_peer,
                    session=session,
                )
                self._sessions[key] = state
                logger.debug("honcho.session_created: key={}", key)
                return state

            except Exception:
                logger.exception("honcho.session_create_failed: key={}", key)
                # Return a bare state so callers don't crash
                state = HonchoSessionState(session_key=key)
                self._sessions[key] = state
                return state

    async def sync_messages(
        self, key: str, messages: list[dict[str, Any]]
    ) -> None:
        """Sync new messages from a Velo session to Honcho.

        Only syncs messages added since last sync (tracked by last_synced_idx).
        Batches up to _MAX_BATCH_SIZE messages per API call.

        Args:
            key: Velo session key.
            messages: Full message list from the Velo session.
        """
        try:
            state = await self.get_or_create(key)
            if state.session is None:
                return

            new_messages = messages[state.last_synced_idx :]
            if not new_messages:
                return

            from honcho import MessageCreateParams

            # Convert Velo messages to Honcho MessageCreateParams
            honcho_msgs: list[Any] = []
            for msg in new_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role not in ("user", "assistant") or not content:
                    continue
                if isinstance(content, list):
                    # Multimodal: extract text parts only
                    text_parts = [
                        c.get("text", "")
                        for c in content
                        if c.get("type") == "text"
                    ]
                    content = " ".join(text_parts)
                if not content.strip():
                    continue
                # Reason: Honcho uses peer_id instead of role. Map user→"user",
                # assistant→ai_peer name to identify message authors.
                peer_id = "user" if role == "user" else self._config.ai_peer
                honcho_msgs.append(
                    MessageCreateParams(
                        content=content[:10000], peer_id=peer_id
                    )
                )

            if not honcho_msgs:
                state.last_synced_idx = len(messages)
                return

            # Batch in chunks of _MAX_BATCH_SIZE
            for i in range(0, len(honcho_msgs), self._MAX_BATCH_SIZE):
                batch = honcho_msgs[i : i + self._MAX_BATCH_SIZE]
                await state.session.aio.add_messages(batch)

            state.last_synced_idx = len(messages)
            logger.debug(
                "honcho.messages_synced: key={} count={}",
                key,
                len(honcho_msgs),
            )

        except Exception:
            logger.exception("honcho.sync_messages_failed: key={}", key)

    async def flush_all(self) -> None:
        """Await pending background tasks and cancel prefetches.

        Called during shutdown to ensure sync tasks complete and
        no fire-and-forget tasks are orphaned.
        """
        # Await tracked sync/prefetch tasks (let them finish gracefully)
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        # Cancel any session-level prefetch tasks
        for state in self._sessions.values():
            if state._prefetch_task and not state._prefetch_task.done():
                state._prefetch_task.cancel()
                try:
                    await state._prefetch_task
                except (asyncio.CancelledError, Exception):
                    pass

    async def shutdown(self) -> None:
        """Close the Honcho client and clean up resources."""
        await self.flush_all()
        # Reason: Honcho sync client doesn't have an async close method.
        # Setting to None releases the httpx client for GC.
        self._client = None
        self._aio = None
        self._sessions.clear()
        logger.info("honcho.shutdown_completed")

    # ------------------------------------------------------------------
    # Context (free, ~200ms) — session.aio.context()
    # ------------------------------------------------------------------

    async def prefetch_context(self, key: str) -> None:
        """Fire-and-forget context prefetch for the next turn.

        Starts a background task that calls session.aio.context() and
        caches the result. The next call to pop_context_result() returns
        the cached value with zero latency.

        Args:
            key: Velo session key.
        """
        state = self._sessions.get(key)
        if not state or state.session is None:
            return

        # Cancel any existing prefetch for this session
        if state._prefetch_task and not state._prefetch_task.done():
            state._prefetch_task.cancel()

        async def _fetch() -> None:
            try:
                kwargs: dict[str, Any] = {}
                if self._config.context_tokens is not None:
                    kwargs["tokens"] = self._config.context_tokens
                ctx = await state.session.aio.context(**kwargs)
                # Reason: SessionContext has .content for the formatted string,
                # but also structured fields. Use str() as fallback.
                state.context_cache = (
                    ctx.content if hasattr(ctx, "content") else str(ctx)
                )
                logger.debug(
                    "honcho.context_prefetched: key={} chars={}",
                    key,
                    len(state.context_cache),
                )
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception(
                    "honcho.context_prefetch_failed: key={}", key
                )

        state._prefetch_task = asyncio.create_task(_fetch())

    def pop_context_result(self, key: str) -> str:
        """Consume and return the prefetched context for a session.

        After calling this, the cache is cleared. Returns empty string
        on cold start (turn 1) or if prefetch hasn't completed.

        Args:
            key: Velo session key.

        Returns:
            Cached user context string, or "" if unavailable.
        """
        state = self._sessions.get(key)
        if not state:
            return ""
        result = state.context_cache
        state.context_cache = ""
        return result

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    async def search_context(self, key: str, query: str) -> str:
        """Semantic search across all Honcho sessions for this user.

        Free operation. Searches the user's message history and peer cards.

        Args:
            key: Velo session key.
            query: Natural language search query.

        Returns:
            Search results as formatted text, or error message.
        """
        try:
            state = await self.get_or_create(key)
            if state.user_peer is None:
                return "No Honcho session available for search."

            # Reason: peer.aio.search returns list[Message] with .content
            results = await state.user_peer.aio.search(query=query)
            if not results:
                return "No relevant context found."

            parts = []
            for r in results[:5]:
                content = r.content if hasattr(r, "content") else str(r)
                parts.append(f"- {content}")
            return "\n".join(parts) if parts else "No relevant context found."

        except Exception:
            logger.exception(
                "honcho.search_context_failed: key={}", key
            )
            return "Error searching user context."

    async def dialectic_query(self, key: str, query: str) -> str:
        """Ask Honcho about the user via dialectic reasoning.

        Costs $0.001-$0.50 per query depending on complexity.

        Args:
            key: Velo session key.
            query: Question about the user.

        Returns:
            Honcho's response about the user, or error message.
        """
        try:
            state = await self.get_or_create(key)
            if state.user_peer is None:
                return "No Honcho session available for query."

            # Reason: peer.aio.chat() returns str | None directly
            response = await state.user_peer.aio.chat(query=query)
            if response is None:
                return "No information available about this user yet."

            content = str(response)

            # Truncate to configured max
            max_chars = self._config.dialectic_max_chars
            if len(content) > max_chars:
                content = content[:max_chars] + "..."

            return content

        except Exception:
            logger.exception(
                "honcho.dialectic_query_failed: key={}", key
            )
            return "Error querying user context."

    async def add_note(self, key: str, content: str) -> None:
        """Record a fact about the user. Triggers Honcho's reasoning pipeline.

        The note is added as a message, which triggers background dreaming
        to update peer cards.

        Args:
            key: Velo session key.
            content: The fact or observation to record.
        """
        try:
            state = await self.get_or_create(key)
            if state.session is None:
                return

            from honcho import MessageCreateParams

            await state.session.aio.add_messages(
                MessageCreateParams(
                    content=f"[note] {content}",
                    peer_id=self._config.ai_peer,
                )
            )
            logger.debug("honcho.note_added: key={}", key)

        except Exception:
            logger.exception("honcho.add_note_failed: key={}", key)
