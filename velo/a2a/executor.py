"""AgentExecutor bridge — connects A2A requests to the velo agent loop."""

from typing import TYPE_CHECKING

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState, TextPart

if TYPE_CHECKING:
    from velo.agent.loop import AgentLoop


class VeloAgentExecutor(AgentExecutor):
    """Bridges A2A task requests to velo's agent loop.

    Each incoming A2A task is processed via ``agent_loop.process_direct()``.
    The task session key is scoped to the A2A task ID so conversation history
    is isolated per task.
    """

    def __init__(self, agent_loop: "AgentLoop") -> None:
        """Initialise with an AgentLoop instance.

        Args:
            agent_loop: AgentLoop instance with a ``process_direct`` coroutine.
        """
        self._loop: "AgentLoop" = agent_loop

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Execute an incoming A2A task.

        Args:
            context: Request context containing the user message and task IDs.
            event_queue: Queue for publishing task state updates.
        """
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        updater.submit()
        updater.start_work()

        text = context.get_user_input()
        session_key = f"a2a:{context.task_id}"

        try:
            result = await self._loop.process_direct(
                content=text,
                session_key=session_key,
                channel="a2a",
                chat_id=session_key,
            )
            updater.update_status(
                TaskState.completed,
                message=updater.new_agent_message(
                    parts=[Part(root=TextPart(text=result or ""))]
                ),
            )
        except Exception as exc:
            updater.update_status(
                TaskState.failed,
                message=updater.new_agent_message(
                    parts=[Part(root=TextPart(text=f"Error processing task: {exc}"))]
                ),
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel an in-progress A2A task.

        Args:
            context: Request context for the task being cancelled.
            event_queue: Queue for publishing the cancellation event.
        """
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        updater.update_status(TaskState.canceled)
