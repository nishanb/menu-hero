"""Workflow primitives: agents built out of other agents."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from agents.core.agent import BaseAgent
from agents.core.context import AgentContext
from agents.schemas.agent import AgentResult

logger = logging.getLogger(__name__)


class SequentialWorkflow(BaseAgent):
    """Runs agents one after another; each agent's response is the next agent's input.

    The workflow is itself an agent, so it can be registered, run, streamed (tool events
    of every step are relayed live) and nested inside other workflows. ``name`` and
    ``description`` can be given per instance; they default to the class-level values.
    """

    name = "sequential_workflow"
    description = "Chains agents; the output of one is the input of the next."

    def __init__(
        self,
        steps: Sequence[BaseAgent],
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        if not steps:
            raise ValueError("SequentialWorkflow needs at least one step")
        self._steps: tuple[BaseAgent, ...] = tuple(steps)
        self._name = name
        self._description = description

    @property
    def agent_name(self) -> str:
        """Instance name override, falling back to the class-level ``name``."""
        return self._name or type(self).name

    @property
    def agent_description(self) -> str:
        """Instance description override, falling back to the class-level ``description``."""
        return self._description or type(self).description

    @property
    def steps(self) -> tuple[BaseAgent, ...]:
        """The agents run in order."""
        return self._steps

    async def run(self, message: str, context: AgentContext | None = None) -> AgentResult:
        """Feed ``message`` through every step and return the last step's response."""
        context = self.prepare_context(message, context)
        current = message
        steps_metadata: list[dict[str, Any]] = []
        for index, agent in enumerate(self._steps):
            logger.debug(
                "workflow %s step %d/%d: %s (run_id=%s)",
                self.agent_name,
                index + 1,
                len(self._steps),
                agent.agent_name,
                context.run_id,
            )
            result = await agent.run(current, context)
            steps_metadata.append(
                {"step": index, "agent": result.agent, "metadata": result.metadata}
            )
            current = result.response
        return AgentResult(
            response=current,
            agent=self.agent_name,
            metadata={"steps": steps_metadata, "agents": [a.agent_name for a in self._steps]},
        )
