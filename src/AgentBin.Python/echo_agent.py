"""EchoAgent executor for AgentBin Python server."""

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import Message, Part, Role


class EchoAgent(AgentExecutor):
    """Simple echo agent that returns the user's message."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Echo back the user's message."""
        text = extract_text(context.message)
        
        reply = Message(
            role=Role.ROLE_AGENT,
            message_id=f"echo-{context.message.message_id}",
            task_id=context.task_id,
            context_id=context.context_id,
            parts=[Part(text=f"Echo: {text}")],
        )
        
        await event_queue.enqueue_event(reply)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel not implemented for echo agent."""
        pass


def extract_text(message: Message) -> str:
    """Extract the first text part from a message."""
    if not message or not message.parts:
        return ""
    
    for part in message.parts:
        if part.HasField("text"):
            return part.text
    
    return ""
