"""Tools and ToolRegistry."""

from __future__ import annotations

from typing import Any

import pytest

from agents.core.context import AgentContext
from agents.core.exceptions import ToolError, ToolNotFoundError
from agents.tools.base import BaseTool, ToolRegistry, build_default_tool_registry
from agents.tools.example_tool import WordCountTool


class BrokenTool(BaseTool):
    name = "broken"

    async def run(self, **kwargs: Any) -> Any:
        raise ValueError("kaput")


async def test_word_count_tool() -> None:
    tool = WordCountTool()
    assert tool.name == "word_count"
    assert await tool.run(text="hello big world") == {"words": 3, "characters": 15}
    assert await tool.run(text="") == {"words": 0, "characters": 0}
    assert await tool.run() == {"words": 0, "characters": 0}


async def test_word_count_tool_rejects_bad_input() -> None:
    tool = WordCountTool()
    with pytest.raises(ToolError):
        await tool.run(text=123)  # type: ignore[arg-type]
    with pytest.raises(ToolError, match="unexpected arguments"):
        await tool.run(text="x", other=1)


def test_tool_registry_register_get_duplicate() -> None:
    registry = ToolRegistry()
    tool = WordCountTool()
    registry.register(tool)
    assert registry.get("word_count") is tool
    assert "word_count" in registry
    assert registry.names() == ["word_count"]
    assert len(registry) == 1
    with pytest.raises(ValueError, match="already registered"):
        registry.register(WordCountTool())


def test_tool_registry_unknown_tool() -> None:
    with pytest.raises(ToolNotFoundError) as excinfo:
        ToolRegistry().get("nope")
    assert str(excinfo.value) == "Unknown tool 'nope'"
    assert excinfo.value.tool == "nope"


def test_default_tool_registry_has_word_count() -> None:
    assert build_default_tool_registry().names() == ["word_count"]


async def test_context_call_tool_unknown_raises_not_found(context: AgentContext) -> None:
    with pytest.raises(ToolNotFoundError):
        await context.call_tool("nope")


async def test_context_call_tool_wraps_tool_exceptions(context: AgentContext) -> None:
    context.tools.register(BrokenTool())
    with pytest.raises(ToolError) as excinfo:
        await context.call_tool("broken", x=1)
    assert isinstance(excinfo.value.__cause__, ValueError)
    assert excinfo.value.tool == "broken"
