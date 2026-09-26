"""Health endpoint (liveness probe used by Docker, nginx and Elastic Beanstalk)."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Return ``{"status": "ok"}`` whenever the process is serving requests."""
    return HealthResponse()
