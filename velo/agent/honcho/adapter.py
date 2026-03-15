"""Honcho adapter: bridge between Velo sessions and the Honcho SDK.

Handles session lifecycle, message sync, context prefetch, dual-peer
observation, identity seeding, peer cards, and dialectic queries.
All public methods degrade gracefully — SDK errors are logged but never
raised to the caller.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from velo.agent.honcho.config import HonchoConfig
from velo.utils.helpers import atomic_write, ensure_dir


def _extract_text(content: str | list[Any]) -> str:
    """Extract plain text from a Velo message content field.

    Handles both string content and multimodal content lists.

    Args:
        content: Message content — either a string or a list of content parts.

    Returns:
        Extracted text string.
    """
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if c.get("type") == "text")
    return content


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
        peer_card_cache: Prefetched peer card for the user.
        peer_card_consumed: Whether peer card was already returned by get_peer_card this turn.
    """

    session_key: str
    user_peer: Any = None
    ai_peer: Any = None
    session: Any = None
    last_synced_idx: int = 0
    context_cache: str = ""
    peer_card_cache: str = ""
    peer_card_consumed: bool = False
    _prefetch_task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def session_id(self) -> str:
        """Extract session ID from Honcho session object."""
        if self.session is None:
            return ""
        return self.session.id if hasattr(self.session, "id") else str(self.session)


class HonchoAdapter:
    """Core bridge between Velo sessions and Honcho SDK.

    Uses Honcho sync client with .aio accessor for async operations.
    All public methods catch exceptions and return empty/False so the
    agent loop is never disrupted by Honcho failures.

    Args:
        config: Honcho configuration.
        workspace: Path to the Velo workspace (for SOUL.md, USER.md sync).
    """

    # Honcho batch limit for add_messages
    _MAX_BATCH_SIZE = 100

    def __init__(self, config: HonchoConfig, workspace: Path | None = None) -> None:
        self._config = config
        self._workspace = workspace
        self._client: Any = None
        self._aio: Any = None  # Honcho async accessor (client.aio)
        self._sessions: dict[str, HonchoSessionState] = {}
        self._lock = asyncio.Lock()
        self._current_session_key: str = ""
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._identity_seeded: set[str] = set()
        self._soul_content: str | None = None  # Cached SOUL.md content
        self._last_card_hash: int = 0  # Change detection for USER.md sync

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
                logger.error("honcho.import_failed: honcho-ai package not installed")
                raise
        return self._aio

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _create_observation(self, peer: Any, session_id: str, content: str) -> bool:
        """Create an observation/conclusion on a peer, with SDK version fallback.

        Tries .observations (SDK v2), then .conclusions (SDK v3), then returns False.

        Args:
            peer: Honcho peer object.
            session_id: Session ID string.
            content: Observation content.

        Returns:
            True if created, False if API unavailable.
        """
        if hasattr(peer.aio, "observations"):
            await peer.aio.observations.create(session_id=session_id, content=content)
            return True
        if hasattr(peer.aio, "conclusions"):
            await peer.aio.conclusions.create(session_id=session_id, content=content)
            return True
        return False

    def _get_soul_content(self) -> str:
        """Read and cache SOUL.md content from workspace.

        Returns:
            SOUL.md content, or "" if unavailable.
        """
        if self._soul_content is not None:
            return self._soul_content
        if not self._workspace:
            return ""
        soul_path = self._workspace / "SOUL.md"
        try:
            self._soul_content = soul_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._soul_content = ""
        return self._soul_content

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def get_or_create(self, key: str) -> HonchoSessionState:
        """Get or create a Honcho session state for the given Velo session key.

        Creates peer and session objects via the Honcho API (get-or-create
        semantics on the server side). Enables dual-peer cross-observation
        and seeds AI identity from SOUL.md on first session.

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
                honcho_id = re.sub(r"[^a-zA-Z0-9_-]", "-", key)
                # Reason: passing metadata={} forces the SDK to make a server-side
                # get-or-create call. Without it, session() only creates a local
                # object and add_messages later fails with 500.
                session = await aio.session(honcho_id, metadata={})

                # Reason: enable cross-observation so each peer forms
                # theory-of-mind of the other. observe_me defaults to True
                # in Honcho, but observe_others must be explicitly enabled.
                if self._config.observe_peers:
                    try:
                        from honcho import SessionPeerConfig

                        await session.aio.add_peers(
                            [
                                (user_peer, SessionPeerConfig(observe_others=True)),
                                (ai_peer, SessionPeerConfig(observe_others=True)),
                            ]
                        )
                    except Exception:
                        # Reason: older SDK versions may not have SessionPeerConfig
                        # or add_peers. Degrade gracefully — observation still works
                        # via observe_me defaults, just without cross-observation.
                        logger.debug(
                            "honcho.add_peers_unavailable: key={} (SDK too old or API changed)", key
                        )

                state = HonchoSessionState(
                    session_key=key,
                    user_peer=user_peer,
                    ai_peer=ai_peer,
                    session=session,
                )
                self._sessions[key] = state

                # Seed AI identity from SOUL.md on first session
                if self._config.seed_identity:
                    await self._seed_ai_identity(state)

                logger.debug("honcho.session_created: key={}", key)
                return state

            except Exception:
                logger.exception("honcho.session_create_failed: key={}", key)
                # Return a bare state so callers don't crash
                state = HonchoSessionState(session_key=key)
                self._sessions[key] = state
                return state

    async def _seed_ai_identity(self, state: HonchoSessionState) -> None:
        """Seed SOUL.md content into the AI peer as an observation.

        Only seeds once per session key (tracked by _identity_seeded).

        Args:
            state: The session state with AI peer to seed.
        """
        if state.session_key in self._identity_seeded:
            return
        if state.ai_peer is None or state.session is None:
            return

        try:
            soul_content = self._get_soul_content()
            if not soul_content.strip():
                return

            created = await self._create_observation(
                state.ai_peer, state.session_id, f"[identity] {soul_content[:5000]}"
            )
            if not created:
                logger.debug("honcho.seed_identity_skipped: no observations/conclusions API")
                return

            self._identity_seeded.add(state.session_key)
            logger.debug("honcho.identity_seeded: key={}", state.session_key)

        except Exception:
            logger.exception("honcho.seed_identity_failed: key={}", state.session_key)

    async def sync_messages(self, key: str, messages: list[dict[str, Any]]) -> None:
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

            honcho_msgs: list[Any] = []
            for msg in new_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role not in ("user", "assistant") or not content:
                    continue
                content = _extract_text(content)
                if not content.strip():
                    continue
                # Reason: Honcho uses peer_id instead of role. Map user->"user",
                # assistant->ai_peer name to identify message authors.
                peer_id = "user" if role == "user" else self._config.ai_peer
                honcho_msgs.append(MessageCreateParams(content=content[:10000], peer_id=peer_id))

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
        fetches the user's peer card in parallel, then caches both.
        Also syncs peer card to USER.md if configured and changed.

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

                # Fetch context and peer card in parallel
                ctx_task = asyncio.create_task(state.session.aio.context(**kwargs))
                card_task = asyncio.create_task(self._fetch_peer_card(state))
                ctx = await ctx_task
                card = await card_task

                # Reason: SessionContext has .content for the formatted string,
                # but also structured fields. Use str() as fallback.
                state.context_cache = ctx.content if hasattr(ctx, "content") else str(ctx)
                state.peer_card_cache = card
                state.peer_card_consumed = False

                logger.debug(
                    "honcho.context_prefetched: key={} ctx_chars={} card_chars={}",
                    key,
                    len(state.context_cache),
                    len(state.peer_card_cache),
                )

                # Sync peer card to USER.md as local cache (skip if unchanged)
                if self._config.sync_peer_card_to_user_md and card:
                    card_hash = hash(card)
                    if card_hash != self._last_card_hash:
                        self._sync_peer_card_to_file(card)
                        self._last_card_hash = card_hash

            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("honcho.context_prefetch_failed: key={}", key)

        state._prefetch_task = asyncio.create_task(_fetch())

    async def _fetch_peer_card(self, state: HonchoSessionState) -> str:
        """Fetch the user peer's card from Honcho.

        Args:
            state: Session state with user_peer.

        Returns:
            Peer card content as string, or "" on failure.
        """
        if state.user_peer is None:
            return ""
        try:
            # Reason: get_card() returns the peer's accumulated profile.
            # Available since Honcho v1.4.1 / SDK v2.3.2.
            card = await state.user_peer.aio.get_card()
            if card is None:
                return ""
            return str(card)
        except (AttributeError, Exception):
            # Reason: older SDK versions may not have get_card().
            logger.debug("honcho.peer_card_unavailable: key={}", state.session_key)
            return ""

    def _sync_peer_card_to_file(self, card_content: str) -> None:
        """Write peer card to workspace/memory/USER.md as local cache.

        Uses shared atomic_write to prevent corruption.

        Args:
            card_content: Peer card text to write.
        """
        if not self._workspace or not card_content.strip():
            return
        try:
            user_md = self._workspace / "memory" / "USER.md"
            ensure_dir(user_md.parent)
            atomic_write(user_md, card_content)
        except Exception:
            logger.exception("honcho.peer_card_sync_failed")

    def pop_context_result(self, key: str) -> str:
        """Consume and return the prefetched context + peer card for a session.

        After calling this, both caches are cleared. Skips peer card if it was
        already consumed by get_peer_card() this turn (avoids sending twice).

        Args:
            key: Velo session key.

        Returns:
            Cached user context string, or "" if unavailable.
        """
        state = self._sessions.get(key)
        if not state:
            return ""
        parts = []
        if state.context_cache:
            parts.append(state.context_cache)
        # Reason: skip peer card if already consumed by honcho_profile tool
        # this turn to avoid sending the same data to the LLM twice.
        if state.peer_card_cache and not state.peer_card_consumed:
            parts.append(f"User Profile (from Honcho):\n{state.peer_card_cache}")
        state.context_cache = ""
        state.peer_card_cache = ""
        state.peer_card_consumed = False
        return "\n\n".join(parts)

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
            logger.exception("honcho.search_context_failed: key={}", key)
            return "Error searching user context."

    async def dialectic_query(
        self, key: str, query: str, peer: Literal["user", "ai"] = "user"
    ) -> str:
        """Ask Honcho about the user or the AI assistant via dialectic reasoning.

        Costs $0.001-$0.50 per query depending on complexity.

        Args:
            key: Velo session key.
            query: Question about the user or AI assistant.
            peer: Which peer to query — "user" (default) or "ai".

        Returns:
            Honcho's response, or error message.
        """
        try:
            state = await self.get_or_create(key)
            target = state.ai_peer if peer == "ai" else state.user_peer
            if target is None:
                return f"No Honcho session available for {peer} query."

            # Reason: peer.aio.chat() returns str | None directly
            response = await target.aio.chat(query=query)
            if response is None:
                return f"No information available about the {peer} yet."

            content = str(response)

            # Truncate to configured max
            max_chars = self._config.dialectic_max_chars
            if len(content) > max_chars:
                content = content[:max_chars] + "..."

            return content

        except Exception:
            logger.exception("honcho.dialectic_query_failed: key={} peer={}", key, peer)
            return "Error querying context."

    async def get_peer_card(self, key: str) -> str:
        """Get the user's peer card (accumulated profile).

        Free and instant — returns cached data if available, otherwise
        fetches from Honcho. Marks the card as consumed so pop_context_result
        won't duplicate it in the runtime context.

        Args:
            key: Velo session key.

        Returns:
            Peer card content, or error/empty message.
        """
        try:
            state = await self.get_or_create(key)
            if state.peer_card_cache:
                state.peer_card_consumed = True
                return state.peer_card_cache
            # Otherwise fetch fresh
            card = await self._fetch_peer_card(state)
            if card:
                state.peer_card_consumed = True
            return card
        except Exception:
            logger.exception("honcho.get_peer_card_failed: key={}", key)
            return "Error retrieving user profile."

    async def add_conclusion(self, key: str, content: str) -> None:
        """Record a structured conclusion about the user.

        Directly updates the user's peer card and representation.
        Falls back to add_messages with [note] prefix if conclusions
        API is unavailable.

        Args:
            key: Velo session key.
            content: The conclusion to record about the user.
        """
        try:
            state = await self.get_or_create(key)
            if state.user_peer is None or state.session is None:
                return

            # Try observations/conclusions API first (stronger than message approach)
            created = await self._create_observation(state.user_peer, state.session_id, content)
            if created:
                logger.debug("honcho.conclusion_added: key={}", key)
                return

            # Fallback: add as a message with [note] prefix
            from honcho import MessageCreateParams

            await state.session.aio.add_messages(
                MessageCreateParams(
                    content=f"[note] {content}",
                    peer_id=self._config.ai_peer,
                )
            )
            logger.debug("honcho.conclusion_added_via_message: key={}", key)

        except Exception:
            logger.exception("honcho.add_conclusion_failed: key={}", key)
