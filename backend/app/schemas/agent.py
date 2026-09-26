"""HTTP schemas of the agent endpoints.

These mirror - but are deliberately distinct from - the framework-agnostic schemas in
``agents.schemas.agent``: the HTTP layer decides what a client may send (e.g. an ``agent``
name, size limits) and converts to the agents package's models in the service layer.
"""

from __future__ import annotations

from typing import Any

import agents as agent_runtime
from pydantic import BaseModel, ConfigDict, Field

AGENT_NAME_PATTERN = r"^[a-z0-9_\-]+$"


class AgentRequest(BaseModel):
    """Body of ``POST /api/agents/run`` and ``POST /api/agents/stream``."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"message": "Hello agent", "agent": "example"}]}
    )

    message: str = Field(
        min_length=1, max_length=10_000, description="The user message for the agent."
    )
    agent: str = Field(
        default="example",
        pattern=AGENT_NAME_PATTERN,
        max_length=64,
        description="Name of a registered agent (see GET /api/agents).",
    )


class AgentResponse(BaseModel):
    """Body of ``POST /api/agents/run``."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "response": "Processed: Hello agent",
                    "agent": "example",
                    "metadata": {"tools_used": ["word_count"], "word_count": 2},
                }
            ]
        }
    )

    response: str = Field(description="The agent's textual answer.")
    agent: str = Field(description="Name of the agent that produced the response.")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Run diagnostics (tools_used, run_id, duration_ms ...)."
    )

    @classmethod
    def from_result(cls, result: agent_runtime.AgentResult) -> AgentResponse:
        """Convert an :class:`agents.AgentResult` into the HTTP response model."""
        return cls(response=result.response, agent=result.agent, metadata=dict(result.metadata))


class AgentInfo(BaseModel):
    """One entry of ``GET /api/agents``."""

    name: str = Field(description="Registered agent name, usable in AgentRequest.agent.")
    description: str = Field(default="", description="Human-readable summary.")

    @classmethod
    def from_info(cls, info: agent_runtime.AgentInfo) -> AgentInfo:
        """Convert an :class:`agents.AgentInfo` registry entry."""
        return cls(name=info.name, description=info.description)


class AgentListResponse(BaseModel):
    """Body of ``GET /api/agents``."""

    agents: list[AgentInfo] = Field(default_factory=list)

    @classmethod
    def from_infos(cls, infos: list[agent_runtime.AgentInfo]) -> AgentListResponse:
        """Build the response from the registry's ``describe()`` output."""
        return cls(agents=[AgentInfo.from_info(info) for info in infos])
