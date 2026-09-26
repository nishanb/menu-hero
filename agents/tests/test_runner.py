"""run_agent / stream_agent."""

from __future__ import annotations

import asyncio

import pytest

from agents.core.agent import BaseAgent
from agents.core.context import AgentContext
from agents.core.events import AgentCompleted, AgentFailed
from agents.core.exceptions import (
    AgentExecutionError,
    AgentNotFoundError,
    AgentTimeoutError,
    ToolNotFoundError,
)
from agents.core.registry import AgentRegistry
from agents.core.runner import run_agent, stream_agent
from agents.schemas.agent import AgentRequest, AgentResult


class SlowAgent(BaseAgent):
    name = "slow"

    async def run(self, message: str, context: AgentContext | None = None) -> AgentResult:
        await asyncio.sleep(1)
        return AgentResult(response="late", agent=self.agent_name)


class InternalTimeoutAgent(BaseAgent):
    """Raises its own TimeoutError; must not be mistaken for the runner's timeout."""

    name = "internal_timeout"

    async def run(self, message: str, context: AgentContext | None = None) -> AgentResult:
        raise TimeoutError("upstream timed out")


class MissingToolAgent(BaseAgent):
    name = "missing_tool"

    async def run(self, message: str, context: AgentContext | None = None) -> AgentResult:
        context = self.prepare_context(message, context)
        await context.call_tool("nope")
        return AgentResult(response="unreachable", agent=self.agent_name)


@pytest.fixture
def custom_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register("slow", SlowAgent)
    registry.register("internal_timeout", InternalTimeoutAgent)
    registry.register("missing_tool", MissingToolAgent)
    return registry


async def test_run_agent_default_example(registry: AgentRegistry) -> None:
    result = await run_agent(AgentRequest(message="Hello agent"), registry=registry)
    assert result.response == "Processed: Hello agent"
    assert result.agent == "example"
    assert result.metadata["tools_used"] == ["word_count"]
    assert result.metadata["word_count"] == 2
    assert isinstance(result.metadata["run_id"], str) and len(result.metadata["run_id"]) == 32
    assert result.metadata["duration_ms"] >= 0


async def test_run_agent_uses_process_default_registry() -> None:
    result = await run_agent(AgentRequest(message="hi"), agent_name="example_workflow")
    assert result.response == "Processed: Processed: hi"


async def test_run_agent_unknown_agent(registry: AgentRegistry) -> None:
    with pytest.raises(AgentNotFoundError, match="Unknown agent 'nope'"):
        await run_agent(AgentRequest(message="hi"), agent_name="nope", registry=registry)


async def test_run_agent_timeout(custom_registry: AgentRegistry) -> None:
    with pytest.raises(AgentTimeoutError) as excinfo:
        await run_agent(
            AgentRequest(message="hi"), agent_name="slow", registry=custom_registry, timeout=0.01
        )
    assert excinfo.value.timeout == 0.01
    assert excinfo.value.agent == "slow"


async def test_run_agent_default_timeout_from_settings(
    custom_registry: AgentRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "0.01")
    with pytest.raises(AgentTimeoutError):
        await run_agent(AgentRequest(message="hi"), agent_name="slow", registry=custom_registry)


async def test_run_agent_internal_timeout_error_is_execution_error(
    custom_registry: AgentRegistry,
) -> None:
    with pytest.raises(AgentExecutionError) as excinfo:
        await run_agent(
            AgentRequest(message="hi"), agent_name="internal_timeout", registry=custom_registry
        )
    assert isinstance(excinfo.value.__cause__, TimeoutError)


async def test_run_agent_propagates_agent_errors_unwrapped(
    custom_registry: AgentRegistry,
) -> None:
    with pytest.raises(ToolNotFoundError):
        await run_agent(
            AgentRequest(message="hi"), agent_name="missing_tool", registry=custom_registry
        )


async def test_stream_agent_event_sequence(registry: AgentRegistry) -> None:
    events = [
        event
        async for event in stream_agent(AgentRequest(message="Hello agent"), registry=registry)
    ]
    assert [event.type for event in events] == [
        "agent_started",
        "tool_started",
        "tool_completed",
        "agent_completed",
    ]
    completed = events[-1]
    assert isinstance(completed, AgentCompleted)
    assert completed.result.response == "Processed: Hello agent"
    assert completed.result.metadata["run_id"] == completed.run_id
    assert completed.result.metadata["tools_used"] == ["word_count"]
    assert "duration_ms" in completed.result.metadata


async def test_stream_agent_unknown_agent(registry: AgentRegistry) -> None:
    with pytest.raises(AgentNotFoundError):
        async for _ in stream_agent(AgentRequest(message="hi"), agent_name="x", registry=registry):
            pass


async def test_stream_agent_failure_becomes_event(custom_registry: AgentRegistry) -> None:
    events = [
        event
        async for event in stream_agent(
            AgentRequest(message="hi"), agent_name="missing_tool", registry=custom_registry
        )
    ]
    assert [event.type for event in events] == ["agent_started", "agent_failed"]
    failed = events[-1]
    assert isinstance(failed, AgentFailed)
    assert failed.error_type == "ToolNotFoundError"
    assert failed.error == "Unknown tool 'nope'"
