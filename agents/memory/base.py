"""Abstract conversation memory interface."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from agents.schemas.messages import Message

logger = logging.getLogger(__name__)


class ConversationMemory(ABC):
    """Stores the turns of a conversation.

    All methods are async so that database- or cache-backed implementations can be
    dropped in without changing agent code.
    """

    @abstractmethod
    async def add(self, message: Message) -> None:
        """Append ``message`` to the conversation."""

    @abstractmethod
    async def history(self, limit: int | None = None) -> list[Message]:
        """Return the conversation in chronological order, optionally only the last ``limit``."""

    @abstractmethod
    async def clear(self) -> None:
        """Forget every stored message."""
