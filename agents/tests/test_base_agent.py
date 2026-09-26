"""BaseAgent contract: abstractness, default stream, failure handling."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

import pytest

from agents.core.agent import BaseAgent
from agents.core.context import AgentContext
from agents.core.events import (
    AgentCompleted,
    AgentEvent,
    AgentFailed,
    AgentStarted,
    CollectingEventEmitter,
    TokenStream,
    ToolCompleted,
    ToolStarted,
)
from agents.core.exceptions import AgentExecutionError
from agents.core.registry import AgentRegistry
from agents.core.runner import run_agent
from agents.schemas.agent import AgentRequest, AgentResult


class EchoAgent(BaseAgent):
    name = "echo"
    description = "Echoes."

    async def run(self, message: str, context: AgentContext | None = None) -> AgentResult:
        context = self.prepare_context(message, context)
        counts = await context.call_tool("word_count", text=message)
        return AgentResult(response=message, agent=self.agent_name, metadata=counts)


class FailingAgent(BaseAgent):
    name = "failing"

    async def run(self, message: str, context: AgentContext | None = None) -> AgentResult:
        raise RuntimeError("boom")


class TokenAgent(BaseAgent):
    """Overrides stream() and implements run() through run_from_stream()."""

    name = "tokens"

    async def run(self, message: str, context: AgentContext | None = None) -> AgentResult:
        return await self.run_from_stream(message, context)

    async def stream(
        self, message: str, context: AgentContext | None = None
    ) -> AsyncIterator[AgentEvent]:
        context = self.prepare_context(message, context)
        yield AgentStarted(run_id=context.run_id, agent=self.agent_name, message=message)
        for word in message.split():
            yield TokenStream(run_id=context.run_id, agent=self.agent_name, token=word)
        yield AgentCompleted(
            run_id=context.run_id,
            agent=self.agent_name,
            result=AgentResult(response=message.upper(), agent=self.agent_name),
        )


def test_base_agent_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseAgent()  # type: ignore[abstract]


async def test_concrete_subclass_runs_without_context() -> None:
    result = await EchoAgent().run("one two")
    assert result.response == "one two"
    assert result.agent == "echo"
    assert result.metadata == {"words": 2, "characters": 7}


async def test_default_stream_emits_started_then_completed() -> None:
    events = [event async for event in EchoAgent().stream("one two")]
    types = [event.type for event in events]
    assert types == ["agent_started", "tool_started", "tool_completed", "agent_completed"]
    assert isinstance(events[0], AgentStarted)
    assert events[0].message == "one two"
    completed = events[-1]
    assert isinstance(completed, AgentCompleted)
    assert completed.result.response == "one two"
    assert {event.run_id for event in events} == {events[0].run_id}
    assert {event.agent for event in events} == {"echo"}


async def test_default_stream_forwards_events_to_caller_emitter() -> None:
    collector = CollectingEventEmitter()
    context = AgentContext.create(AgentRequest(message="x y z"), events=collector)
    streamed = [event async for event in EchoAgent().stream("x y z", context)]
    assert [event.type for event in collector.events] == ["tool_started", "tool_completed"]
    assert isinstance(collector.events[0], ToolStarted)
    assert isinstance(collector.events[1], ToolCompleted)
    assert collector.events[1].duration_ms >= 0
    assert all(event.run_id == context.run_id for event in streamed)


async def test_failing_agent_stream_ends_with_agent_failed() -> None:
    events = [event async for event in FailingAgent().stream("hello")]
    assert [event.type for event in events] == ["agent_started", "agent_failed"]
    failed = events[-1]
    assert isinstance(failed, AgentFailed)
    assert failed.error == "boom"
    assert failed.error_type == "RuntimeError"


async def test_failing_agent_run_agent_raises_execution_error() -> None:
    registry = AgentRegistry()
    registry.register("failing", FailingAgent)
    with pytest.raises(AgentExecutionError) as excinfo:
        await run_agent(AgentRequest(message="hello"), agent_name="failing", registry=registry)
    assert isinstance(excinfo.value.__cause__, RuntimeError)
    assert excinfo.value.agent == "failing"


async def test_stream_cancels_run_task_when_consumer_stops_early() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowAgent(BaseAgent):
        name = "slow"

        async def run(self, message: str, context: AgentContext | None = None) -> AgentResult:
            started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return AgentResult(response="late", agent=self.agent_name)

    stream = SlowAgent().stream("hello")
    assert isinstance(stream, AsyncGenerator)
    first = await anext(stream)
    assert first.type == "agent_started"
    await stream.aclose()
    assert not cancelled.is_set()  # the run task only starts once the consumer resumes

    stream = SlowAgent().stream("hello")
    assert isinstance(stream, AsyncGenerator)
    await anext(stream)
    consume = asyncio.ensure_future(anext(stream))
    await started.wait()
    consume.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consume
    await stream.aclose()
    assert cancelled.is_set()


async def test_run_from_stream_returns_result_and_forwards_events() -> None:
    collector = CollectingEventEmitter()
    context = AgentContext.create(AgentRequest(message="a b"), events=collector)
    result = await TokenAgent().run("a b", context)
    assert result.response == "A B"
    assert [event.type for event in collector.events] == ["agent_started", "token", "token"]


def test_agent_name_property_reflects_class_variable() -> None:
    assert EchoAgent().agent_name == "echo"
    assert EchoAgent().agent_description == "Echoes."
