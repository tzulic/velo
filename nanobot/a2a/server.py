"""A2A ASGI server with Bearer-auth middleware and uvicorn integration."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .card import build_agent_card
from .executor import NanobotAgentExecutor

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.config.schema import A2AConfig


class _BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests missing the expected Bearer token.

    Well-known paths (agent discovery) are always public.
    When ``api_key`` is empty, all requests are allowed through.
    """

    def __init__(self, app: Any, api_key: str) -> None:
        """Initialise middleware.

        Args:
            app: The wrapped ASGI application.
            api_key: Expected Bearer token value. Empty string disables auth.
        """
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """Enforce Bearer-token auth on non-discovery endpoints.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware/handler in the chain.

        Returns:
            HTTP response, potentially 401 Unauthorized.
        """
        if self.api_key and not request.url.path.startswith("/.well-known"):
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {self.api_key}":
                return Response("Unauthorized", status_code=401)
        return await call_next(request)


def _build_a2a_app(a2a_config: "A2AConfig", workspace: Path, agent_loop: "AgentLoop") -> Any:
    """Build the A2A ASGI application with auth middleware.

    Args:
        a2a_config: A2AConfig with server settings.
        workspace: Path to nanobot workspace (used for skill discovery).
        agent_loop: AgentLoop instance for processing tasks.

    Returns:
        ASGI application wrapped with Bearer-auth middleware.
    """
    card = build_agent_card(a2a_config, workspace)
    handler = DefaultRequestHandler(
        agent_executor=NanobotAgentExecutor(agent_loop),
        task_store=InMemoryTaskStore(),
    )
    starlette_app = A2AStarletteApplication(
        agent_card=card,
        http_handler=handler,
    ).build()
    return _BearerAuthMiddleware(starlette_app, a2a_config.api_key)


async def start_a2a_server(a2a_config: "A2AConfig", workspace: Path, agent_loop: "AgentLoop") -> None:
    """Run the A2A server as an asyncio task alongside the main gateway.

    Installs no signal handlers to avoid conflicts with the gateway's signal
    handling. The coroutine completes when the asyncio task is cancelled.

    Args:
        a2a_config: A2AConfig with port and auth settings.
        workspace: Path to nanobot workspace.
        agent_loop: AgentLoop instance for processing tasks.
    """
    app = _build_a2a_app(a2a_config, workspace, agent_loop)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=a2a_config.port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    # Disable uvicorn's own signal handlers — the gateway manages shutdown.
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    await server.serve()
