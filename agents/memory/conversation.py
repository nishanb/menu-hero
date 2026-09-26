"""In-process conversation memory (per run / per process, not persistent)."""

from __future__ import annotations

import logging

from agents.memory.base import ConversationMemory
from agents.schemas.messages import Message

logger = logging.getLogger(__name__)


class InMemoryConversationMemory(ConversationMemory):
    """Keeps messages in a Python list, optionally capped to the most recent ``max_messages``."""

    def __init__(self, max_messages: int | None = None) -> None:
        if max_messages is not None and max_messages < 1:
            raise ValueError("max_messages must be a positive integer or None")
        self._max_messages = max_messages
        self._messages: list[Message] = []

    async def add(self, message: Message) -> None:
        """Append ``message``, evicting the oldest turns beyond ``max_messages``."""
        self._messages.append(message)
        if self._max_messages is not None and len(self._messages) > self._max_messages:
            del self._messages[: len(self._messages) - self._max_messages]

    async def history(self, limit: int | None = None) -> list[Message]:
        """Return a copy of the stored messages (the last ``limit`` when given)."""
        if limit is None:
            return list(self._messages)
        if limit < 0:
            raise ValueError("limit must be non-negative or None")
        return self._messages[-limit:] if limit else []

    async def clear(self) -> None:
        """Drop every stored message."""
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)
