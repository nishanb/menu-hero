"""Reference agent that exercises memory, tools and events without calling a model."""

from __future__ import annotations

import logging

from agents.core.agent import BaseAgent
from agents.core.context import AgentContext
from agents.schemas.agent import AgentResult
from agents.schemas.messages import Message

logger = logging.getLogger(__name__)


class ExampleAgent(BaseAgent):
    """Echoes the message back with a ``Processed:`` prefix, counting words on the way."""

    name = "example"
    description = "Echoes the message back with a 'Processed:' prefix."

    async def run(self, message: str, context: AgentContext | None = None) -> AgentResult:
        """Store the turn in memory, call the ``word_count`` tool and return the echo."""
        context = self.prepare_context(message, context)
        await context.memory.add(Message(role="user", content=message))
        counts = await context.call_tool("word_count", text=message)
        response = f"Processed: {message}"
        await context.memory.add(
            Message(role="assistant", content=response, metadata={"agent": self.agent_name})
        )
        logger.debug(
            "example agent processed %d words (run_id=%s)", counts["words"], context.run_id
        )
        return AgentResult(
            response=response,
            agent=self.agent_name,
            metadata={
                "tools_used": ["word_count"],
                "word_count": counts["words"],
                "characters": counts["characters"],
            },
        )
