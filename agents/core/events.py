"""Agent event model and event emitters.

Events are the streaming preview of an agent run: lifecycle events are produced by
:meth:`agents.core.agent.BaseAgent.stream`, tool events by
:meth:`agents.core.context.AgentContext.call_tool`, token events by streaming agents.
The ``type`` field is a Literal discriminator so the whole family can be parsed with
:func:`parse_event` (or serialised one event per SSE message by the HTTP layer).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from agents.schemas.agent import AgentResult
from agents.schemas.messages import utcnow

logger = logging.getLogger(__name__)


class AgentEvent(BaseModel):
    """Base class of every event emitted during an agent run."""

    model_config = ConfigDict(extra="forbid")

    type: str
    run_id: str
    agent: str
    timestamp: datetime = Field(default_factory=utcnow)


class AgentStarted(AgentEvent):
    """The agent has started processing ``message``."""

    type: Literal["agent_started"] = "agent_started"
    message: str


class ToolStarted(AgentEvent):
    """A tool invocation has begun."""

    type: Literal["tool_started"] = "tool_started"
    tool: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolCompleted(AgentEvent):
    """A tool invocation finished successfully."""

    type: Literal["tool_completed"] = "tool_completed"
    tool: str
    output: Any = None
    duration_ms: float


class TokenStream(AgentEvent):
    """A partial response token, for agents that stream model output."""

    type: Literal["token"] = "token"
    token: str


class AgentCompleted(AgentEvent):
    """The agent finished; ``result`` is the final :class:`AgentResult`."""

    type: Literal["agent_completed"] = "agent_completed"
    result: AgentResult


class AgentFailed(AgentEvent):
    """The agent raised; ``error_type`` is the exception class name."""

    type: Literal["agent_failed"] = "agent_failed"
    error: str
    error_type: str


AnyAgentEvent = Annotated[
    AgentStarted | ToolStarted | ToolCompleted | TokenStream | AgentCompleted | AgentFailed,
    Field(discriminator="type"),
]

_event_adapter: TypeAdapter[AnyAgentEvent] = TypeAdapter(AnyAgentEvent)


def parse_event(data: str | bytes | dict[str, Any]) -> AnyAgentEvent:
    """Parse a serialised event (JSON text/bytes or a dict) into its concrete event class."""
    if isinstance(data, dict):
        return _event_adapter.validate_python(data)
    return _event_adapter.validate_json(data)


@runtime_checkable
class EventEmitter(Protocol):
    """Anything that can receive agent events (the sink side of streaming)."""

    async def emit(self, event: AgentEvent) -> None:
        """Deliver ``event`` to the sink."""
        ...


class NullEventEmitter:
    """Discards every event. Default emitter of a plain (non-streaming) run."""

    async def emit(self, event: AgentEvent) -> None:
        """Ignore ``event``."""
        return None


class CollectingEventEmitter:
    """Keeps every event in a list; handy for tests and post-run inspection."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def emit(self, event: AgentEvent) -> None:
        """Append ``event`` to :attr:`events`."""
        self.events.append(event)

    def clear(self) -> None:
        """Forget all collected events."""
        self.events.clear()


class QueueEventEmitter:
    """Relays events through an :class:`asyncio.Queue` so a consumer can stream them live.

    Optionally forwards every event to a ``downstream`` emitter as well, which is how
    :meth:`BaseAgent.stream` layers live streaming on top of a caller-provided emitter.
    Iterate the emitter (``async for event in emitter``) to consume events until
    :meth:`close` has been called and the queue is drained.
    """

    def __init__(self, downstream: EventEmitter | None = None) -> None:
        self._queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        self._downstream = downstream
        self._closed = False

    @property
    def closed(self) -> bool:
        """True once :meth:`close` has been called (no further events are queued)."""
        return self._closed

    async def emit(self, event: AgentEvent) -> None:
        """Queue ``event`` for the consumer and forward it downstream."""
        if self._closed:
            logger.debug("event emitted after close, forwarded downstream only: %s", event.type)
        else:
            self._queue.put_nowait(event)
        if self._downstream is not None:
            await self._downstream.emit(event)

    def close(self) -> None:
        """Signal the consumer that no more events will follow (idempotent)."""
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(None)

    async def __aiter__(self) -> AsyncIterator[AgentEvent]:
        """Yield queued events until the close sentinel is reached."""
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item
