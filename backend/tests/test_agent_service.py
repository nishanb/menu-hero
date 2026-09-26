"""AgentService and InProcessAgentExecutor, without any HTTP."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import agents
import pytest
from agents import (
    AgentContext,
    AgentEvent,
    AgentNotFoundError,
    AgentRegistry,
    AgentTimeoutError,
    BaseAgent,
)

from app.schemas.agent import AgentListResponse, AgentRequest, AgentResponse
from app.services.agent_service import AgentService, InProcessAgentExecutor


class FakeExecutor:
    """Records what the service hands it and returns canned data."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, agents.AgentRequest]] = []
        self.error = error

    async def execute(self, agent_name: str, request: agents.AgentRequest) -> agents.AgentResult:
        self.calls.append((agent_name, request))
        if self.error is not None:
            raise self.error
        return agents.AgentResult(
            response=f"fake:{request.message}", agent=agent_name, metadata={"run_id": "abc"}
        )

    def stream(self, agent_name: str, request: agents.AgentRequest) -> AsyncIterator[AgentEvent]:
        self.calls.append((agent_name, request))
        return self._events(agent_name, request)

    @staticmethod
    async def _events(agent_name: str, request: agents.AgentRequest) -> AsyncIterator[AgentEvent]:
        yield agents.AgentStarted(run_id="r1", agent=agent_name, message=request.message)
        yield agents.AgentCompleted(
            run_id="r1",
            agent=agent_name,
            result=agents.AgentResult(response="done", agent=agent_name),
        )

    def list_agents(self) -> list[agents.AgentInfo]:
        return [agents.AgentInfo(name="fake", description="A fake agent")]


async def test_run_maps_schemas_and_delegates() -> None:
    executor = FakeExecutor()
    service = AgentService(executor)

    response = await service.run(AgentRequest(message="Hello", agent="fake"))

    assert isinstance(response, AgentResponse)
    assert response.response == "fake:Hello"
    assert response.agent == "fake"
    assert response.metadata == {"run_id": "abc"}

    ((agent_name, request),) = executor.calls
    assert agent_name == "fake"
    assert isinstance(request, agents.AgentRequest)
    assert request.message == "Hello"
    assert request.conversation_id is None


async def test_run_propagates_agent_errors() -> None:
    service = AgentService(FakeExecutor(error=AgentTimeoutError("slow", agent="fake")))
    with pytest.raises(AgentTimeoutError):
        await service.run(AgentRequest(message="Hello", agent="fake"))


async def test_stream_relays_executor_events() -> None:
    executor = FakeExecutor()
    service = AgentService(executor)

    events = [event async for event in service.stream(AgentRequest(message="hi", agent="fake"))]

    assert [event.type for event in events] == ["agent_started", "agent_completed"]
    assert executor.calls[0][0] == "fake"
    assert executor.calls[0][1].message == "hi"


def test_list_agents_maps_to_response_model() -> None:
    listing = AgentService(FakeExecutor()).list_agents()
    assert isinstance(listing, AgentListResponse)
    assert listing.model_dump() == {"agents": [{"name": "fake", "description": "A fake agent"}]}


class SlowAgent(BaseAgent):
    """Never finishes within a test's patience."""

    name = "slow"
    description = "Sleeps."

    async def run(self, message: str, context: AgentContext | None = None) -> agents.AgentResult:
        await asyncio.sleep(5)
        return agents.AgentResult(response="late", agent=self.name)


def _registry() -> AgentRegistry:
    registry = agents.build_default_registry()
    registry.register(SlowAgent.name, SlowAgent, description=SlowAgent.description)
    return registry


async def test_in_process_executor_runs_example_agent() -> None:
    executor = InProcessAgentExecutor(_registry())
    result = await executor.execute("example", agents.AgentRequest(message="Hello agent"))
    assert result.response == "Processed: Hello agent"
    assert result.agent == "example"
    assert "run_id" in result.metadata


def test_in_process_executor_stream_rejects_unknown_agent_synchronously() -> None:
    executor = InProcessAgentExecutor(_registry())
    with pytest.raises(AgentNotFoundError, match="Unknown agent 'nope'"):
        executor.stream("nope", agents.AgentRequest(message="hi"))


async def test_in_process_executor_stream_event_order() -> None:
    executor = InProcessAgentExecutor(_registry())
    events = [e async for e in executor.stream("example", agents.AgentRequest(message="hi"))]
    assert [e.type for e in events] == [
        "agent_started",
        "tool_started",
        "tool_completed",
        "agent_completed",
    ]


async def test_in_process_executor_execute_timeout() -> None:
    executor = InProcessAgentExecutor(_registry(), timeout=0.05)
    with pytest.raises(AgentTimeoutError):
        await executor.execute("slow", agents.AgentRequest(message="hi"))


async def test_in_process_executor_stream_timeout() -> None:
    executor = InProcessAgentExecutor(_registry(), timeout=0.05)
    seen: list[str] = []
    with pytest.raises(AgentTimeoutError):
        async for event in executor.stream("slow", agents.AgentRequest(message="hi")):
            seen.append(event.type)
    assert seen == ["agent_started"]
    # The agent task was cancelled with the stream: nothing is left running.
    await asyncio.sleep(0)
    assert not [t for t in asyncio.all_tasks() if t.get_name().startswith("agent-run:")]


def test_in_process_executor_default_timeout_comes_from_agent_settings() -> None:
    executor = InProcessAgentExecutor(_registry())
    assert executor.timeout == agents.get_settings().agent_timeout_seconds
