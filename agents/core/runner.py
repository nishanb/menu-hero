"""Entry points for executing agents: :func:`run_agent` and :func:`stream_agent`.

These are what the HTTP layer calls today and what queue workers will call tomorrow.
They own registry lookup, context creation, timeouts and error normalisation so callers
only ever see :class:`AgentError` subclasses.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from agents.core.config import get_settings
from agents.core.context import AgentContext
from agents.core.events import AgentCompleted, AgentEvent
from agents.core.exceptions import AgentError, AgentExecutionError, AgentTimeoutError
from agents.core.registry import AgentRegistry, get_default_registry
from agents.schemas.agent import AgentRequest, AgentResult

logger = logging.getLogger(__name__)


def _finalise(result: AgentResult, *, run_id: str, started: float) -> AgentResult:
    """Return ``result`` with ``run_id`` and ``duration_ms`` merged into its metadata."""
    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    metadata = {**result.metadata, "run_id": run_id, "duration_ms": duration_ms}
    return result.model_copy(update={"metadata": metadata})


async def run_agent(
    request: AgentRequest,
    *,
    agent_name: str = "example",
    registry: AgentRegistry | None = None,
    timeout: float | None = None,
) -> AgentResult:
    """Run the agent registered as ``agent_name`` on ``request`` and return its result.

    * ``timeout`` (seconds) defaults to ``AgentSettings.agent_timeout_seconds``.
    * Unknown agents raise :class:`AgentNotFoundError`; timeouts raise
      :class:`AgentTimeoutError`; any other non-``AgentError`` exception is wrapped in
      :class:`AgentExecutionError` (chained).
    * ``run_id`` and ``duration_ms`` are added to ``result.metadata``.
    """
    registry = registry if registry is not None else get_default_registry()
    agent = registry.create(agent_name)
    context = AgentContext.create(request, agent=agent_name)
    effective_timeout = timeout if timeout is not None else get_settings().agent_timeout_seconds
    logger.info(
        "agent run started: agent=%s run_id=%s timeout=%ss",
        agent_name,
        context.run_id,
        effective_timeout,
    )
    started = time.perf_counter()
    scope = asyncio.timeout(effective_timeout)
    try:
        async with scope:
            result = await agent.run(request.message, context)
    except TimeoutError as exc:
        if scope.expired():
            logger.warning("agent run timed out: agent=%s run_id=%s", agent_name, context.run_id)
            raise AgentTimeoutError(
                f"Agent '{agent_name}' timed out after {effective_timeout}s",
                agent=agent_name,
                timeout=effective_timeout,
            ) from exc
        raise AgentExecutionError(f"Agent '{agent_name}' failed: {exc}", agent=agent_name) from exc
    except AgentError as exc:
        logger.warning(
            "agent run failed: agent=%s run_id=%s error=%s", agent_name, context.run_id, exc
        )
        raise
    except Exception as exc:
        logger.exception("agent run crashed: agent=%s run_id=%s", agent_name, context.run_id)
        raise AgentExecutionError(f"Agent '{agent_name}' failed: {exc}", agent=agent_name) from exc
    final = _finalise(result, run_id=context.run_id, started=started)
    logger.info(
        "agent run completed: agent=%s run_id=%s duration_ms=%s",
        agent_name,
        context.run_id,
        final.metadata["duration_ms"],
    )
    return final


async def stream_agent(
    request: AgentRequest,
    *,
    agent_name: str = "example",
    registry: AgentRegistry | None = None,
) -> AsyncIterator[AgentEvent]:
    """Stream the events of running ``agent_name`` on ``request``.

    Unknown agents raise :class:`AgentNotFoundError` before the first event. Failures
    during the run surface as an ``AgentFailed`` event (the stream never raises for them).
    The ``AgentCompleted`` result carries ``run_id``/``duration_ms`` like :func:`run_agent`.
    """
    registry = registry if registry is not None else get_default_registry()
    agent = registry.create(agent_name)
    context = AgentContext.create(request, agent=agent_name)
    logger.info("agent stream started: agent=%s run_id=%s", agent_name, context.run_id)
    started = time.perf_counter()
    async for event in agent.stream(request.message, context):
        if isinstance(event, AgentCompleted):
            result = _finalise(event.result, run_id=context.run_id, started=started)
            yield event.model_copy(update={"result": result})
        else:
            yield event
    logger.info("agent stream finished: agent=%s run_id=%s", agent_name, context.run_id)
