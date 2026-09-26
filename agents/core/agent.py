"""Base class every agent derives from."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import ClassVar

from agents.core.context import AgentContext
from agents.core.events import (
    AgentCompleted,
    AgentEvent,
    AgentFailed,
    AgentStarted,
    QueueEventEmitter,
)
from agents.core.exceptions import AgentExecutionError
from agents.schemas.agent import AgentRequest, AgentResult

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """An agent turns a message into an :class:`AgentResult`, optionally streaming events.

    Subclasses set the ``name``/``description`` class variables and implement :meth:`run`.
    Streaming comes for free: the default :meth:`stream` runs :meth:`run` in a task and
    relays every event the agent emits through its context. Agents that produce tokens
    incrementally may override :meth:`stream` and implement :meth:`run` via
    :meth:`run_from_stream`.
    """

    name: ClassVar[str] = "base"
    description: ClassVar[str] = ""

    @property
    def agent_name(self) -> str:
        """Name reported in results and events (the ``name`` class variable by default)."""
        return type(self).name

    @property
    def agent_description(self) -> str:
        """Human-readable description (the ``description`` class variable by default)."""
        return type(self).description

    @abstractmethod
    async def run(self, message: str, context: AgentContext | None = None) -> AgentResult:
        """Process ``message`` and return the result.

        ``context`` may be ``None``; use :meth:`prepare_context` to obtain a usable one.
        """

    def prepare_context(self, message: str, context: AgentContext | None) -> AgentContext:
        """Return a context for this agent: a default one when ``None``, else a view stamped
        with this agent's name (sharing memory, tools and events with the caller)."""
        if context is None:
            request = AgentRequest(message=message)
            return AgentContext.create(request, agent=self.agent_name)
        return context.for_agent(self.agent_name)

    async def stream(
        self, message: str, context: AgentContext | None = None
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent and yield its events live.

        Yields ``AgentStarted`` first, then every event the agent emits through
        ``context.events`` while :meth:`run` executes (tool events, tokens ...), and finally
        ``AgentCompleted(result)`` or ``AgentFailed(error, error_type)``. Events emitted by
        the agent are also forwarded to the emitter the caller put in ``context``.
        """
        context = self.prepare_context(message, context)
        relay = QueueEventEmitter(downstream=context.events)
        run_context = context.with_events(relay)
        yield AgentStarted(run_id=context.run_id, agent=self.agent_name, message=message)

        async def _run() -> AgentResult:
            try:
                return await self.run(message, run_context)
            finally:
                relay.close()

        task = asyncio.create_task(_run(), name=f"agent-run:{self.agent_name}:{context.run_id}")
        try:
            async for event in relay:
                yield event
            result = await task
        except Exception as exc:
            logger.exception("agent %s failed (run_id=%s)", self.agent_name, context.run_id)
            yield AgentFailed(
                run_id=context.run_id,
                agent=self.agent_name,
                error=str(exc) or type(exc).__name__,
                error_type=type(exc).__name__,
            )
            return
        finally:
            if not task.done():
                task.cancel()
                await asyncio.wait([task])
        yield AgentCompleted(run_id=context.run_id, agent=self.agent_name, result=result)

    async def run_from_stream(
        self, message: str, context: AgentContext | None = None
    ) -> AgentResult:
        """Implement :meth:`run` for agents that override :meth:`stream`.

        Consumes :meth:`stream`, forwards every intermediate event to ``context.events`` so
        non-streaming callers still observe them, and returns the final result (or raises
        :class:`AgentExecutionError` when the stream ends with ``AgentFailed``).
        Never combine with the default :meth:`stream`, which itself calls :meth:`run`.
        """
        context = self.prepare_context(message, context)
        async for event in self.stream(message, context):
            if isinstance(event, AgentCompleted):
                return event.result
            if isinstance(event, AgentFailed):
                raise AgentExecutionError(
                    f"{event.error_type}: {event.error}", agent=self.agent_name
                )
            await context.emit(event)
        raise AgentExecutionError(
            f"Agent '{self.agent_name}' stream ended without a terminal event",
            agent=self.agent_name,
        )
