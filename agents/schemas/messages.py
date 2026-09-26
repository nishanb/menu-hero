"""Conversation message schema used by memory backends and (future) LLM prompts."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

Role = Literal["user", "assistant", "system", "tool"]


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


class Message(BaseModel):
    """A single conversation turn.

    ``role`` follows the usual chat convention (``user``/``assistant``/``system``/``tool``);
    ``metadata`` is free-form and intended for things like tool names or token counts.
    """

    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str
    timestamp: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
