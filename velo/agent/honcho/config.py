"""Honcho integration configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class HonchoConfig(BaseModel):
    """Configuration for the Honcho user-modeling integration.

    When enabled (default for Volos customers), Honcho provides persistent
    cross-session user modeling via its cloud API. Local MEMORY.md is retained
    for agent-specific operational notes (hybrid mode).

    Args:
        enabled: Master switch. True by default for Volos deployments.
        api_key: Honcho API key (or proxy token for Volos customers).
        api_base: Honcho API endpoint (overridden by Volos proxy).
        workspace_id: Honcho workspace for tenant isolation.
        ai_peer: Name of the AI peer in Honcho sessions.
        write_frequency: When to sync messages — async (fire-and-forget),
            turn (await each sync), or session (batch at end).
        recall_mode: How context is injected — hybrid (context + tools),
            context (system prompt only), or tools (agent-invoked only).
        context_tokens: Token budget for get_context(). None = Honcho default.
        dialectic_reasoning_level: Depth for .chat() queries.
        dialectic_max_chars: Max chars returned from dialectic queries.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    enabled: bool = True
    api_key: str = ""
    api_base: str = "https://api.honcho.dev"
    workspace_id: str = "default"
    ai_peer: str = "velo"
    write_frequency: Literal["async", "turn", "session"] = "async"
    recall_mode: Literal["hybrid", "context", "tools"] = "hybrid"
    context_tokens: int | None = Field(default=None, description="Token budget for get_context()")
    dialectic_reasoning_level: str = "low"
    dialectic_max_chars: int = 600
    observe_peers: bool = True
    seed_identity: bool = True
    sync_peer_card_to_user_md: bool = True
