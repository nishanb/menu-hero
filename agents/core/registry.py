"""Agent registry: maps agent names to factories."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from agents.core.agent import BaseAgent
from agents.core.exceptions import AgentNotFoundError
from agents.schemas.agent import AgentInfo

logger = logging.getLogger(__name__)

AgentFactory = Callable[[], BaseAgent]


@dataclass(frozen=True)
class _Registration:
    factory: AgentFactory
    description: str


class AgentRegistry:
    """Name → factory table. Factories build a fresh agent instance per run."""

    def __init__(self) -> None:
        self._entries: dict[str, _Registration] = {}

    def register(self, name: str, factory: AgentFactory, *, description: str = "") -> None:
        """Register ``factory`` under ``name``; raises ``ValueError`` when already registered."""
        if not name:
            raise ValueError("Agent name must not be empty")
        if name in self._entries:
            raise ValueError(f"Agent '{name}' is already registered")
        self._entries[name] = _Registration(factory=factory, description=description)
        logger.debug("registered agent %s", name)

    def create(self, name: str) -> BaseAgent:
        """Instantiate the agent registered as ``name`` or raise :class:`AgentNotFoundError`."""
        try:
            entry = self._entries[name]
        except KeyError:
            raise AgentNotFoundError(name) from None
        return entry.factory()

    def names(self) -> list[str]:
        """Registered names in registration order."""
        return list(self._entries)

    def describe(self) -> list[AgentInfo]:
        """Name and description of every registered agent."""
        return [
            AgentInfo(name=name, description=entry.description)
            for name, entry in self._entries.items()
        ]

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)


def build_default_registry() -> AgentRegistry:
    """Create a registry with the built-in agents: ``example`` and ``example_workflow``."""
    # Imported lazily: the implementations import BaseAgent from this package.
    from agents.implementations.example_agent import ExampleAgent
    from agents.workflows.example_workflow import (
        EXAMPLE_WORKFLOW_DESCRIPTION,
        EXAMPLE_WORKFLOW_NAME,
        build_example_workflow,
    )

    registry = AgentRegistry()
    registry.register(ExampleAgent.name, ExampleAgent, description=ExampleAgent.description)
    registry.register(
        EXAMPLE_WORKFLOW_NAME, build_example_workflow, description=EXAMPLE_WORKFLOW_DESCRIPTION
    )
    return registry


_default_registry: AgentRegistry | None = None


def get_default_registry() -> AgentRegistry:
    """Return the process-wide registry, building it on first use."""
    global _default_registry
    if _default_registry is None:
        _default_registry = build_default_registry()
    return _default_registry


def reset_default_registry() -> None:
    """Forget the cached default registry (mainly for tests)."""
    global _default_registry
    _default_registry = None
