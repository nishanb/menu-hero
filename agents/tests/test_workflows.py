"""SequentialWorkflow and the example workflow."""

from __future__ import annotations

import pytest

from agents.core.context import AgentContext
from agents.implementations.example_agent import ExampleAgent
from agents.schemas.agent import AgentRequest
from agents.workflows.base import SequentialWorkflow
from agents.workflows.example_workflow import build_example_workflow


async def test_example_workflow_chains_two_example_agents() -> None:
    workflow = build_example_workflow()
    result = await workflow.run("hi")
    assert result.response == "Processed: Processed: hi"
    assert result.agent == "example_workflow"
    assert result.metadata["agents"] == ["example", "example"]
    assert [step["agent"] for step in result.metadata["steps"]] == ["example", "example"]
    assert result.metadata["steps"][1]["metadata"]["word_count"] == 2


async def test_workflow_shares_context_and_streams_step_events() -> None:
    context = AgentContext.create(AgentRequest(message="hi"))
    events = [event async for event in build_example_workflow().stream("hi", context)]
    assert [event.type for event in events] == [
        "agent_started",
        "tool_started",
        "tool_completed",
        "tool_started",
        "tool_completed",
        "agent_completed",
    ]
    assert events[0].agent == "example_workflow"
    assert events[1].agent == "example"
    assert len(await context.memory.history()) == 4


def test_workflow_names() -> None:
    default = SequentialWorkflow([ExampleAgent()])
    assert default.agent_name == "sequential_workflow"
    assert default.agent_description
    custom = SequentialWorkflow([ExampleAgent()], name="custom", description="d")
    assert custom.agent_name == "custom"
    assert custom.agent_description == "d"
    assert len(custom.steps) == 1


def test_workflow_requires_steps() -> None:
    with pytest.raises(ValueError):
        SequentialWorkflow([])
