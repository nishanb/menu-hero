"""Agent endpoints: list, run, and stream (server-sent events).

The handlers only translate HTTP <-> :class:`app.services.agent_service.AgentService`;
agent execution lives behind the service.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from agents import AgentEvent, AgentTimeoutError
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.dependencies.agents import AgentServiceDep
from app.schemas.agent import AgentListResponse, AgentRequest, AgentResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents")

SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # tell nginx not to buffer the stream
}

NOT_FOUND_DETAIL = {"detail": "Unknown agent 'nope'"}
FAILED_DETAIL = {"detail": "Agent execution failed"}
TIMEOUT_DETAIL = {"detail": "Agent timed out"}


def _json_response_doc(description: str, example: dict[str, str]) -> dict[str, Any]:
    return {"description": description, "content": {"application/json": {"example": example}}}


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: _json_response_doc("Unknown agent", NOT_FOUND_DETAIL),
    500: _json_response_doc("Agent failed", FAILED_DETAIL),
    504: _json_response_doc("Agent timed out", TIMEOUT_DETAIL),
}


def format_sse(event_type: str, data: str) -> str:
    """Encode one server-sent-events message."""
    return f"event: {event_type}\ndata: {data}\n\n"


async def _sse_stream(events: AsyncIterator[AgentEvent]) -> AsyncIterator[str]:
    """Serialise agent events as SSE messages.

    Errors raised *inside* the stream (after the 200 response has started) cannot become
    HTTP status codes any more, so they end the stream with an ``error`` message carrying
    the same ``detail`` the JSON endpoints would use - never internals.
    """
    try:
        async for event in events:
            yield format_sse(event.type, event.model_dump_json())
    except AgentTimeoutError as exc:
        logger.warning("agent stream timed out: %s", exc)
        yield format_sse("error", json.dumps(TIMEOUT_DETAIL))
    except Exception:
        logger.exception("agent stream failed")
        yield format_sse("error", json.dumps(FAILED_DETAIL))


@router.get("", response_model=AgentListResponse, summary="List registered agents")
async def list_agents(service: AgentServiceDep) -> AgentListResponse:
    """Names and descriptions of every agent that can be run."""
    return service.list_agents()


@router.post(
    "/run",
    response_model=AgentResponse,
    responses=ERROR_RESPONSES,
    summary="Run an agent and wait for its result",
)
async def run_agent(request: AgentRequest, service: AgentServiceDep) -> AgentResponse:
    """Run ``request.agent`` on ``request.message`` and return the final result."""
    return await service.run(request)


@router.post(
    "/stream",
    responses={
        200: {"description": "Server-sent events", "content": {SSE_MEDIA_TYPE: {}}},
        **ERROR_RESPONSES,
    },
    summary="Run an agent and stream its events (SSE)",
)
async def stream_agent(request: AgentRequest, service: AgentServiceDep) -> StreamingResponse:
    """Stream ``agent_started``, tool events and ``agent_completed``/``agent_failed``.

    Each message is ``event: <type>\\ndata: <event JSON>\\n\\n``.
    """
    events = service.stream(request)  # raises AgentNotFoundError -> 404 before streaming
    return StreamingResponse(_sse_stream(events), media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS)
