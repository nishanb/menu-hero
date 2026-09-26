"""Exception hierarchy for the agents package.

Every error raised on purpose by this package derives from :class:`AgentError`, so callers
(HTTP layer, CLI, workers) can map the whole family to a single failure path while still
distinguishing the interesting cases (not found, timeout, tool and LLM problems).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class AgentError(Exception):
    """Base class for all errors raised by the agents package."""

    def __init__(self, message: str = "Agent error", *, agent: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.agent = agent

    def __str__(self) -> str:
        return self.message


class AgentNotFoundError(AgentError):
    """Raised when a registry lookup for an agent name fails."""

    def __init__(self, agent: str) -> None:
        super().__init__(f"Unknown agent '{agent}'", agent=agent)


class AgentExecutionError(AgentError):
    """Raised when an agent fails while running (wraps the original exception as cause)."""


class AgentTimeoutError(AgentError):
    """Raised when an agent does not finish within the configured timeout."""

    def __init__(
        self,
        message: str = "Agent timed out",
        *,
        agent: str | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(message, agent=agent)
        self.timeout = timeout


class ToolError(AgentError):
    """Raised when a tool invocation fails (wraps the original exception as cause)."""

    def __init__(
        self, message: str = "Tool error", *, tool: str | None = None, agent: str | None = None
    ) -> None:
        super().__init__(message, agent=agent)
        self.tool = tool


class ToolNotFoundError(ToolError):
    """Raised when a tool name is not present in the :class:`ToolRegistry`."""

    def __init__(self, tool: str) -> None:
        super().__init__(f"Unknown tool '{tool}'", tool=tool)


class LLMError(AgentError):
    """Raised for failures talking to a language-model provider."""

    def __init__(
        self, message: str = "LLM error", *, provider: str | None = None, agent: str | None = None
    ) -> None:
        super().__init__(message, agent=agent)
        self.provider = provider


class LLMNotConfiguredError(LLMError):
    """Raised when the selected LLM provider is not implemented or lacks credentials."""
