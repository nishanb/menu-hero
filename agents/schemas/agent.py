"""Public request/result schemas for running agents.

These are the framework-agnostic contracts consumed by the HTTP layer, the CLI and
(future) background workers. They deliberately contain only plain data.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class AgentRequest(BaseModel):
    """What a caller sends to an agent: the user message plus optional context."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, description="The user message to process.")
    conversation_id: str | None = Field(
        default=None, description="Optional conversation identifier for multi-turn memory."
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Free-form caller metadata, copied into the run context."
    )


class AgentResult(BaseModel):
    """What an agent returns: the response text, which agent produced it and metadata."""

    model_config = ConfigDict(extra="forbid")

    response: str = Field(description="The agent's textual answer.")
    agent: str = Field(description="Name of the agent that produced the response.")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Diagnostics such as tools_used, run_id and duration_ms.",
    )


class AgentInfo(BaseModel):
    """Descriptive entry for an agent registered in an :class:`AgentRegistry`."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
