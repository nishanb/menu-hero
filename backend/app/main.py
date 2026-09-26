"""FastAPI application factory.

``uvicorn app.main:app`` serves the module-level ``app``; tests call :func:`create_app`
directly. The API (and its docs) live under ``settings.api_prefix`` (``/api``) because the
production nginx routes only ``/api/`` to this process - everything else goes to Nuxt.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from agents import AgentError, AgentNotFoundError, AgentTimeoutError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from app import __version__
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import close_client, get_database
from app.core.logging import setup_logging
from app.models.indexes import ensure_indexes
from app.services.errors import ManagementError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure logging on startup and release the MongoDB client on shutdown."""
    settings: Settings = app.state.settings
    setup_logging(settings.log_level)
    logger.info(
        "%s %s starting: env=%s api_prefix=%s database=%s",
        settings.project_name,
        __version__,
        settings.app_env,
        settings.api_prefix,
        "configured" if settings.database_configured else "not configured",
    )
    if settings.google_oauth_configured and not settings.oauth_hosts_match:
        logger.warning(
            "GOOGLE_REDIRECT_URI (%s) and FRONTEND_BASE_URL (%s) have different hostnames; "
            "the session cookie will be set on the callback's host and the frontend will "
            "never send it back",
            settings.google_redirect_uri,
            settings.frontend_base_url,
        )
    if settings.database_configured:
        try:
            await ensure_indexes(get_database())
        except PyMongoError as exc:
            # A database that is merely unreachable at boot must not stop the process:
            # nothing connects eagerly, and the first request surfaces the problem.
            logger.warning("could not ensure mongodb indexes at startup: %s", exc)
    try:
        yield
    finally:
        await close_client()
        logger.info("%s stopped", settings.project_name)


async def _management_refused(request: Request, exc: Exception) -> JSONResponse:
    """Turn a management domain error into the API's ``{"detail": ...}`` body.

    The messages are written for the caller (an owner or an admin using the app), so they
    are returned verbatim; the status code comes from the exception class.
    """
    status_code = exc.status_code if isinstance(exc, ManagementError) else 400
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


async def _agent_not_found(request: Request, exc: Exception) -> JSONResponse:
    """404 for an unregistered agent name."""
    agent = exc.agent if isinstance(exc, AgentNotFoundError) else None
    return JSONResponse(status_code=404, content={"detail": f"Unknown agent '{agent}'"})


async def _agent_timed_out(request: Request, exc: Exception) -> JSONResponse:
    """504 when the agent exceeded its time budget."""
    logger.warning("agent timed out: %s", exc)
    return JSONResponse(status_code=504, content={"detail": "Agent timed out"})


async def _agent_failed(request: Request, exc: Exception) -> JSONResponse:
    """500 for any other agents-package error; the traceback is logged, never returned."""
    logger.error("agent execution failed: %s", exc, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Agent execution failed"})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application from ``settings`` (defaults to :func:`get_settings`)."""
    settings = settings if settings is not None else get_settings()
    prefix = settings.api_prefix

    app = FastAPI(
        title=settings.project_name,
        version=__version__,
        lifespan=lifespan,
        docs_url=f"{prefix}/docs",
        redoc_url=f"{prefix}/redoc",
        openapi_url=f"{prefix}/openapi.json",
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Starlette picks the handler by walking the exception's MRO, so the specific
    # subclasses win over the AgentError catch-all regardless of registration order.
    app.add_exception_handler(AgentNotFoundError, _agent_not_found)
    app.add_exception_handler(AgentTimeoutError, _agent_timed_out)
    app.add_exception_handler(AgentError, _agent_failed)
    app.add_exception_handler(ManagementError, _management_refused)

    app.include_router(api_router, prefix=prefix)
    return app


app = create_app()
