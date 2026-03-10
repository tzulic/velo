"""A2A client — sends tasks to a remote A2A peer agent."""

from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import Message, MessageSendParams, Part, Role, SendMessageRequest, TextPart


def _extract_response_text(response: object) -> str:
    """Extract the final agent text from a send_message response.

    Walks the task history in reverse looking for the most recent agent
    message.  Defensive against variations in SDK response structure.

    Args:
        response: Return value from ``A2AClient.send_message()``.

    Returns:
        Extracted text, or empty string if none found.
    """
    try:
        # SendMessageResponse has .result (Task), or the response may be the Task.
        task = getattr(response, "result", response)
        history = getattr(task, "history", None) or []
        for msg in reversed(history):
            role = getattr(msg, "role", None)
            role_val = role.value if hasattr(role, "value") else str(role)
            if role_val in ("agent", "assistant"):
                for part in getattr(msg, "parts", []) or []:
                    # Part may be Part(root=TextPart) or TextPart directly.
                    inner = getattr(part, "root", part)
                    text = getattr(inner, "text", None)
                    if text:
                        return str(text)
    except Exception:
        pass
    return ""


async def send_task_to_peer(peer_url: str, api_key: str, task: str) -> str:
    """Send a task to a remote A2A agent and return its text response.

    Card discovery uses a public (unauthenticated) HTTP client since
    ``/.well-known/`` endpoints are always open.  The actual task request
    uses an authenticated client with the Bearer token.

    Args:
        peer_url: Base URL of the peer A2A server, e.g. ``http://1.2.3.4:18791``.
        api_key: Bearer token for the peer (empty string means no auth).
        task: Natural-language task description to send.

    Returns:
        Text response from the peer agent.

    Raises:
        httpx.HTTPError: On network or HTTP-level failures.
        Exception: If the SDK raises any other error.
    """
    # Phase 1: discover agent card (public, no auth)
    async with httpx.AsyncClient() as public_http:
        resolver = A2ACardResolver(httpx_client=public_http, base_url=peer_url)
        agent_card = await resolver.get_agent_card()

    # Phase 2: send task (authenticated)
    auth_headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(headers=auth_headers) as auth_http:
        client = A2AClient(httpx_client=auth_http, agent_card=agent_card)
        request = SendMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(
                message=Message(
                    role=Role.user,
                    parts=[Part(root=TextPart(text=task))],
                    messageId=uuid4().hex,
                )
            ),
        )
        response = await client.send_message(request)
        return _extract_response_text(response)
