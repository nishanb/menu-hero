"""Per-run execution context handed to agents.

The context bundles the live collaborators of one run (memory, tools, event emitter) with
the request and a ``run_id``. It is a plain dataclass rather than a pydantic model because
it holds behaviourful objects, not data.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import uuid4

from agents.core.events import (
    AgentEvent,
    EventEmitter,
    NullEventEmitter,
    ToolCompleted,
    ToolStarted,
)
from agents.core.exceptions import ToolError
from agents.memory.base import ConversationMemory
from agents.memory.conversation import InMemoryConversationMemory
from agents.schemas.agent import AgentRequest
from agents.tools.base import ToolRegistry, build_default_tool_registry

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """Everything an agent needs during one run.

    ``agent`` is the name of the agent currently using the context; it is stamped on the
    events produced by :meth:`call_tool`. :meth:`agents.core.agent.BaseAgent.prepare_context`
    derives a per-agent view (sharing memory, tools and events) so nested agents report
    under their own name.
    """

    request: AgentRequest
    run_id: str
    memory: ConversationMemory
    tools: ToolRegistry
    events: EventEmitter
    metadata: dict[str, Any] = field(default_factory=dict)
    agent: str = ""

    @classmethod
    def create(
        cls,
        request: AgentRequest,
        *,
        memory: ConversationMemory | None = None,
        tools: ToolRegistry | None = None,
        events: EventEmitter | None = None,
        run_id: str | None = None,
        agent: str = "",
    ) -> AgentContext:
        """Build a context with sensible defaults (fresh in-memory memory, default tools)."""
        return cls(
            request=request,
            run_id=run_id or uuid4().hex,
            memory=memory if memory is not None else InMemoryConversationMemory(),
            tools=tools if tools is not None else build_default_tool_registry(),
            events=events if events is not None else NullEventEmitter(),
            metadata=dict(request.metadata),
            agent=agent,
        )

    def for_agent(self, agent: str) -> AgentContext:
        """Return a view of this context stamped with ``agent`` (shares every collaborator)."""
        if self.agent == agent:
            return self
        return replace(self, agent=agent)

    def with_events(self, events: EventEmitter) -> AgentContext:
        """Return a view of this context whose events go to ``events`` instead."""
        return replace(self, events=events)

    async def emit(self, event: AgentEvent) -> None:
        """Send ``event`` to the run's event emitter."""
        await self.events.emit(event)

    async def call_tool(self, name: str, **kwargs: Any) -> Any:
        """Run the tool registered as ``name`` and emit ``ToolStarted``/``ToolCompleted``.

        Raises :class:`ToolNotFoundError` for unknown tools and wraps any other failure of
        the tool in :class:`ToolError` (chained to the original exception).
        """
        tool = self.tools.get(name)
        await self.emit(ToolStarted(run_id=self.run_id, agent=self.agent, tool=name, input=kwargs))
        started = time.perf_counter()
        try:
            output = await tool.run(**kwargs)
        except ToolError:
            raise
        except Exception as exc:
            logger.exception("tool %s failed (run_id=%s)", name, self.run_id)
            raise ToolError(f"Tool '{name}' failed: {exc}", tool=name, agent=self.agent) from exc
        duration_ms = (time.perf_counter() - started) * 1000
        await self.emit(
            ToolCompleted(
                run_id=self.run_id,
                agent=self.agent,
                tool=name,
                output=output,
                duration_ms=duration_ms,
            )
        )
        logger.debug("tool %s completed in %.2fms (run_id=%s)", name, duration_ms, self.run_id)
        return output
