"""Agent execution service.

Layering::

    route -> AgentService -> AgentExecutor -> agents.run_agent() / agents.stream_agent()

* :class:`AgentService` owns the translation between the HTTP schemas
  (``app.schemas.agent``) and the agents package's models, plus logging. It knows nothing
  about HTTP objects and nothing about *where* the agent runs.
* :class:`AgentExecutor` is the swap point. :class:`InProcessAgentExecutor` runs the agent
  inside the web process today. A future ``QueuedAgentExecutor`` implements the same
  Protocol by publishing ``(agent_name, agents.AgentRequest)`` as a job to a queue and
  awaiting the ``agents.AgentResult`` (or relaying the ``AgentEvent`` stream) that a worker
  produces by calling the very same ``agents.run_agent()`` / ``agents.stream_agent()``.
  Switching executors is a one-line change in ``app/dependencies/agents.py``; routes,
  schemas and the ``agents`` package stay untouched.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Protocol

import agents
from agents import AgentError, AgentEvent, AgentNotFoundError, AgentRegistry, AgentTimeoutError

from app.schemas.agent import AgentListResponse, AgentRequest, AgentResponse

logger = logging.getLogger(__name__)


class AgentExecutor(Protocol):
    """Runs agents somewhere (this process today, a worker tier tomorrow).

    Implementations must raise :class:`agents.AgentNotFoundError` for an unknown agent -
    from :meth:`execute` when awaited and from :meth:`stream` *synchronously*, before any
    event is produced, so the HTTP layer can still answer 404 instead of a 200 stream.
    """

    async def execute(self, agent_name: str, request: agents.AgentRequest) -> agents.AgentResult:
        """Run ``agent_name`` on ``request`` to completion."""
        ...

    def stream(self, agent_name: str, request: agents.AgentRequest) -> AsyncIterator[AgentEvent]:
        """Run ``agent_name`` on ``request`` and yield its events as they happen."""
        ...

    def list_agents(self) -> list[agents.AgentInfo]:
        """Describe every agent this executor can run."""
        ...


async def _with_deadline(
    events: AsyncIterator[AgentEvent], *, agent_name: str, timeout: float
) -> AsyncIterator[AgentEvent]:
    """Relay ``events`` but abort with :class:`AgentTimeoutError` after ``timeout`` seconds.

    ``agents.stream_agent`` applies no timeout itself. The deadline is enforced around each
    ``__anext__`` call (never around a ``yield``), which cancels the underlying agent task
    cleanly and closes the source generator.
    """
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            try:
                event = await asyncio.wait_for(anext(events), max(remaining, 0.0))
            except StopAsyncIteration:
                return
            except TimeoutError as exc:
                raise AgentTimeoutError(
                    f"Agent '{agent_name}' stream exceeded {timeout}s",
                    agent=agent_name,
                    timeout=timeout,
                ) from exc
            yield event
    finally:
        aclose = getattr(events, "aclose", None)
        if aclose is not None:
            await aclose()


class InProcessAgentExecutor:
    """Executes agents in the current process via the ``agents`` runner functions."""

    def __init__(
        self, registry: AgentRegistry | None = None, *, timeout: float | None = None
    ) -> None:
        """``registry`` defaults to the process-wide one; ``timeout`` (seconds) to
        ``AGENT_TIMEOUT_SECONDS`` from the agents settings."""
        self._registry = registry if registry is not None else agents.get_default_registry()
        self._timeout = timeout

    @property
    def timeout(self) -> float:
        """Effective wall-clock limit for one run."""
        if self._timeout is not None:
            return self._timeout
        return agents.get_settings().agent_timeout_seconds

    async def execute(self, agent_name: str, request: agents.AgentRequest) -> agents.AgentResult:
        """Delegate to :func:`agents.run_agent` (registry lookup, timeout, error wrapping)."""
        return await agents.run_agent(
            request, agent_name=agent_name, registry=self._registry, timeout=self.timeout
        )

    def stream(self, agent_name: str, request: agents.AgentRequest) -> AsyncIterator[AgentEvent]:
        """Delegate to :func:`agents.stream_agent`, adding the run deadline."""
        if agent_name not in self._registry:
            raise AgentNotFoundError(agent_name)
        events = agents.stream_agent(request, agent_name=agent_name, registry=self._registry)
        return _with_deadline(events, agent_name=agent_name, timeout=self.timeout)

    def list_agents(self) -> list[agents.AgentInfo]:
        """Describe the registry."""
        return self._registry.describe()


class AgentService:
    """Use-case layer for the agent endpoints: schema mapping, logging, delegation."""

    def __init__(self, executor: AgentExecutor) -> None:
        self._executor = executor

    @staticmethod
    def _to_agent_request(request: AgentRequest) -> agents.AgentRequest:
        """Map the HTTP body onto the agents package's request model."""
        return agents.AgentRequest(message=request.message)

    async def run(self, request: AgentRequest) -> AgentResponse:
        """Run the requested agent and return the HTTP response model.

        ``agents.AgentError`` subclasses propagate unchanged; ``app.main`` maps them to
        HTTP status codes.
        """
        started = time.perf_counter()
        try:
            result = await self._executor.execute(request.agent, self._to_agent_request(request))
        except AgentError as exc:
            logger.warning(
                "agent run failed: agent=%s error_type=%s", request.agent, type(exc).__name__
            )
            raise
        logger.info(
            "agent run completed: agent=%s run_id=%s duration_ms=%.1f",
            result.agent,
            result.metadata.get("run_id"),
            (time.perf_counter() - started) * 1000,
        )
        return AgentResponse.from_result(result)

    def stream(self, request: AgentRequest) -> AsyncIterator[AgentEvent]:
        """Return the live event stream of the requested agent run.

        Raises ``agents.AgentNotFoundError`` immediately for an unknown agent.
        """
        events = self._executor.stream(request.agent, self._to_agent_request(request))
        return self._log_stream(request.agent, events)

    @staticmethod
    async def _log_stream(
        agent_name: str, events: AsyncIterator[AgentEvent]
    ) -> AsyncIterator[AgentEvent]:
        started = time.perf_counter()
        count = 0
        async for event in events:
            count += 1
            yield event
        logger.info(
            "agent stream completed: agent=%s events=%d duration_ms=%.1f",
            agent_name,
            count,
            (time.perf_counter() - started) * 1000,
        )

    def list_agents(self) -> AgentListResponse:
        """List the agents the executor can run."""
        return AgentListResponse.from_infos(self._executor.list_agents())
