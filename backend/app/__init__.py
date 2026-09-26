"""Menu Hero backend: the FastAPI application (import root ``app``).

Request path: HTTP -> ``app.api.routes`` -> ``app.services.agent_service.AgentService``
-> ``AgentExecutor`` -> ``agents.run_agent()``. Routes never contain agent logic.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
