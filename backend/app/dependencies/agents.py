"""Dependency provider for :class:`app.services.agent_service.AgentService`.

This is the single place that decides *how* agents are executed: swap
:class:`InProcessAgentExecutor` for a queue-backed executor here and nothing else changes.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.services.agent_service import AgentService, InProcessAgentExecutor


@lru_cache(maxsize=1)
def get_agent_service() -> AgentService:
    """Return the process-wide :class:`AgentService` (built on first use)."""
    return AgentService(InProcessAgentExecutor())


AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
"""Route parameter annotation: ``service: AgentServiceDep``."""
