"""Conversation memory."""

from __future__ import annotations

import pytest

from agents.memory.base import ConversationMemory
from agents.memory.conversation import InMemoryConversationMemory
from agents.schemas.messages import Message


def test_memory_base_is_abstract() -> None:
    with pytest.raises(TypeError):
        ConversationMemory()  # type: ignore[abstract]


async def test_add_history_clear() -> None:
    memory = InMemoryConversationMemory()
    await memory.add(Message(role="user", content="one"))
    await memory.add(Message(role="assistant", content="two"))
    await memory.add(Message(role="user", content="three"))
    history = await memory.history()
    assert [m.content for m in history] == ["one", "two", "three"]
    assert [m.content for m in await memory.history(limit=2)] == ["two", "three"]
    assert await memory.history(limit=0) == []
    assert len(memory) == 3
    await memory.clear()
    assert await memory.history() == []


async def test_history_returns_a_copy() -> None:
    memory = InMemoryConversationMemory()
    await memory.add(Message(role="user", content="one"))
    history = await memory.history()
    history.clear()
    assert len(await memory.history()) == 1


async def test_max_messages_evicts_oldest() -> None:
    memory = InMemoryConversationMemory(max_messages=2)
    for content in ("a", "b", "c"):
        await memory.add(Message(role="user", content=content))
    assert [m.content for m in await memory.history()] == ["b", "c"]


async def test_invalid_arguments() -> None:
    with pytest.raises(ValueError):
        InMemoryConversationMemory(max_messages=0)
    with pytest.raises(ValueError):
        await InMemoryConversationMemory().history(limit=-1)
