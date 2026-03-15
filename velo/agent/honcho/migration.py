"""Migration helpers for bootstrapping Honcho from existing local data.

Three functions for existing users activating Honcho for the first time:
upload prior messages, seed USER.md content as conclusions, and seed
SOUL.md into the AI peer.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from velo.agent.honcho.adapter import HonchoAdapter


async def migrate_local_history(
    adapter: HonchoAdapter, key: str, messages: list[dict[str, Any]]
) -> bool:
    """Upload prior session messages to Honcho as XML-formatted history.

    Wraps each message in XML tags so Honcho can distinguish them from
    live conversation. Skips system/tool messages.

    Args:
        adapter: HonchoAdapter with active client.
        key: Velo session key for the user.
        messages: Prior conversation messages to upload.

    Returns:
        True on success, False on failure.
    """
    if not messages:
        return True

    try:
        state = await adapter.get_or_create(key)
        if state.session is None:
            logger.warning("honcho.migrate_history_skipped: no session for key={}", key)
            return False

        from honcho import MessageCreateParams

        # Format as XML history block
        lines = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role not in ("user", "assistant") or not content:
                continue
            if isinstance(content, list):
                text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                content = " ".join(text_parts)
            if not content.strip():
                continue
            ts = msg.get("timestamp", "")
            lines.append(f"<message role='{role}' ts='{ts}'>{content[:2000]}</message>")

        if not lines:
            return True

        # Reason: upload as a single large message from the AI peer so Honcho
        # processes it as background context, not as a live conversation.
        history_block = "<prior_history>\n" + "\n".join(lines) + "\n</prior_history>"
        await state.session.aio.add_messages(
            MessageCreateParams(
                content=history_block[:50000],
                peer_id=adapter._config.ai_peer,
            )
        )
        logger.info("honcho.migrate_history_completed: key={} messages={}", key, len(lines))
        return True

    except Exception:
        logger.exception("honcho.migrate_history_failed: key={}", key)
        return False


async def migrate_memory_files(adapter: HonchoAdapter, key: str, workspace: Path) -> bool:
    """Upload USER.md content as conclusions about the user and seed SOUL.md.

    Reads USER.md and creates observations/conclusions on the user peer.
    Also calls seed_ai_identity for SOUL.md.

    Args:
        adapter: HonchoAdapter with active client.
        key: Velo session key for the user.
        workspace: Path to the Velo workspace.

    Returns:
        True on success, False on failure.
    """
    try:
        state = await adapter.get_or_create(key)
        if state.user_peer is None or state.session is None:
            logger.warning("honcho.migrate_memory_skipped: no session for key={}", key)
            return False

        # Upload USER.md as conclusions about the user
        user_md = workspace / "memory" / "USER.md"
        if user_md.exists():
            user_content = user_md.read_text(encoding="utf-8").strip()
            if user_content:
                peer = state.user_peer
                session_id = (
                    state.session.id if hasattr(state.session, "id") else str(state.session)
                )
                if hasattr(peer.aio, "observations"):
                    await peer.aio.observations.create(
                        session_id=session_id,
                        content=f"[migrated_profile] {user_content[:5000]}",
                    )
                elif hasattr(peer.aio, "conclusions"):
                    await peer.aio.conclusions.create(
                        session_id=session_id,
                        content=f"[migrated_profile] {user_content[:5000]}",
                    )
                else:
                    # Fallback: add as message
                    from honcho import MessageCreateParams

                    await state.session.aio.add_messages(
                        MessageCreateParams(
                            content=f"[migrated_profile] {user_content[:5000]}",
                            peer_id=adapter._config.ai_peer,
                        )
                    )
                logger.info("honcho.migrate_user_md_completed: key={}", key)

        # Seed SOUL.md into AI peer
        await seed_ai_identity(adapter, key, workspace)

        return True

    except Exception:
        logger.exception("honcho.migrate_memory_failed: key={}", key)
        return False


async def seed_ai_identity(adapter: HonchoAdapter, key: str, workspace: Path) -> bool:
    """Seed SOUL.md content into AI peer (idempotent).

    Reads SOUL.md from workspace and creates an observation on the AI peer.
    Safe to call multiple times — the adapter tracks seeded sessions.

    Args:
        adapter: HonchoAdapter with active client.
        key: Velo session key.
        workspace: Path to the Velo workspace containing SOUL.md.

    Returns:
        True on success, False on failure.
    """
    try:
        state = await adapter.get_or_create(key)
        # Delegate to the adapter's internal seeding method
        await adapter._seed_ai_identity(state)
        return True
    except Exception:
        logger.exception("honcho.seed_ai_identity_failed: key={}", key)
        return False
