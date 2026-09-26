"""Settings for the agents package (LLM provider, credentials, timeouts).

Values come from environment variables, falling back to ``.env`` files: the repo-root
``.env`` (resolved relative to this module: ``../../.env``) first, then ``./.env`` in the
current working directory; environment variables always win. Unknown keys in the shared
``.env`` (backend/frontend settings) are ignored.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

LLMProvider = Literal["stub", "openai", "anthropic", "google"]

REPO_ROOT_ENV_FILE: Path = Path(__file__).resolve().parent.parent.parent / ".env"
"""Repo-root ``.env`` shared with the backend (``agents/core/config.py`` → ``../../.env``)."""


class AgentSettings(BaseSettings):
    """Runtime configuration of the agent system (server-side only, never sent to browsers)."""

    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT_ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    llm_api_key: SecretStr | None = Field(
        default=None, description="API key for the selected provider (LLM_API_KEY)."
    )
    llm_provider: LLMProvider = Field(
        default="stub", description="Which LLM backend to use (LLM_PROVIDER); only 'stub' exists."
    )
    llm_model: str | None = Field(
        default=None, description="Provider-specific model name (LLM_MODEL)."
    )
    agent_timeout_seconds: float = Field(
        default=60,
        gt=0,
        description="Default wall-clock limit for a single agent run (AGENT_TIMEOUT_SECONDS).",
    )

    @property
    def llm_configured(self) -> bool:
        """True when a real (non-stub) provider is selected and an API key is present."""
        if self.llm_provider == "stub":
            return False
        return self.llm_api_key is not None and bool(self.llm_api_key.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> AgentSettings:
    """Return the process-wide :class:`AgentSettings` instance (built on first use)."""
    settings = AgentSettings()
    logger.debug(
        "agent settings loaded: provider=%s model=%s timeout=%ss",
        settings.llm_provider,
        settings.llm_model,
        settings.agent_timeout_seconds,
    )
    return settings


def reset_settings() -> None:
    """Drop the cached settings so the next :func:`get_settings` call re-reads the environment."""
    get_settings.cache_clear()
