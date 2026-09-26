"""ExampleAgent behaviour."""

from __future__ import annotations

from agents.core.context import AgentContext
from agents.core.events import AgentCompleted, CollectingEventEmitter, ToolCompleted, ToolStarted
from agents.implementations.example_agent import ExampleAgent
from agents.schemas.agent import AgentRequest


async def test_run_returns_processed_message(context: AgentContext) -> None:
    result = await ExampleAgent().run("hello", context)
    assert result.response == "Processed: hello"
    assert result.agent == "example"
    assert result.metadata == {"tools_used": ["word_count"], "word_count": 1, "characters": 5}


async def test_run_without_context_creates_a_default_one() -> None:
    result = await ExampleAgent().run("hello world")
    assert result.response == "Processed: hello world"
    assert result.metadata["word_count"] == 2
    assert result.metadata["characters"] == 11


async def test_run_stores_both_turns_in_memory(context: AgentContext) -> None:
    await ExampleAgent().run("hello", context)
    history = await context.memory.history()
    assert [message.role for message in history] == ["user", "assistant"]
    assert history[0].content == "hello"
    assert history[1].content == "Processed: hello"
    assert history[1].metadata == {"agent": "example"}


async def test_run_emits_tool_events_to_context_emitter(
    context: AgentContext, collector: CollectingEventEmitter
) -> None:
    await ExampleAgent().run("hello", context)
    assert [event.type for event in collector.events] == ["tool_started", "tool_completed"]
    started, completed = collector.events
    assert isinstance(started, ToolStarted)
    assert started.tool == "word_count"
    assert started.input == {"text": "hello"}
    assert started.agent == "example"
    assert isinstance(completed, ToolCompleted)
    assert completed.output == {"words": 1, "characters": 5}
    assert completed.duration_ms >= 0


async def test_stream_yields_tool_events_between_start_and_completion() -> None:
    context = AgentContext.create(AgentRequest(message="hi there"))
    events = [event async for event in ExampleAgent().stream("hi there", context)]
    assert [event.type for event in events] == [
        "agent_started",
        "tool_started",
        "tool_completed",
        "agent_completed",
    ]
    completed = events[-1]
    assert isinstance(completed, AgentCompleted)
    assert completed.result.response == "Processed: hi there"
    assert completed.result.metadata["word_count"] == 2
    assert all(event.run_id == context.run_id for event in events)


def test_example_agent_metadata() -> None:
    assert ExampleAgent.name == "example"
    assert ExampleAgent.description == "Echoes the message back with a 'Processed:' prefix."
