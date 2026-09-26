"""AgentRegistry behaviour."""

from __future__ import annotations

import pytest

from agents.core.exceptions import AgentNotFoundError
from agents.core.registry import (
    AgentRegistry,
    build_default_registry,
    get_default_registry,
    reset_default_registry,
)
from agents.implementations.example_agent import ExampleAgent
from agents.schemas.agent import AgentInfo
from agents.workflows.base import SequentialWorkflow


def test_register_and_create() -> None:
    registry = AgentRegistry()
    registry.register("example", ExampleAgent, description="desc")
    assert "example" in registry
    assert registry.names() == ["example"]
    assert registry.describe() == [AgentInfo(name="example", description="desc")]
    assert isinstance(registry.create("example"), ExampleAgent)
    assert registry.create("example") is not registry.create("example")
    assert len(registry) == 1


def test_duplicate_registration_raises() -> None:
    registry = AgentRegistry()
    registry.register("example", ExampleAgent)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("example", ExampleAgent)


def test_empty_name_rejected() -> None:
    with pytest.raises(ValueError):
        AgentRegistry().register("", ExampleAgent)


def test_unknown_agent_raises_not_found() -> None:
    registry = AgentRegistry()
    with pytest.raises(AgentNotFoundError) as excinfo:
        registry.create("missing")
    assert str(excinfo.value) == "Unknown agent 'missing'"
    assert excinfo.value.agent == "missing"
    assert "missing" not in registry


def test_default_registry_contents() -> None:
    registry = build_default_registry()
    assert registry.names() == ["example", "example_workflow"]
    assert isinstance(registry.create("example"), ExampleAgent)
    workflow = registry.create("example_workflow")
    assert isinstance(workflow, SequentialWorkflow)
    assert workflow.agent_name == "example_workflow"
    descriptions = {info.name: info.description for info in registry.describe()}
    assert descriptions["example"] == ExampleAgent.description
    assert descriptions["example_workflow"]


def test_get_default_registry_is_cached() -> None:
    first = get_default_registry()
    assert get_default_registry() is first
    reset_default_registry()
    assert get_default_registry() is not first
