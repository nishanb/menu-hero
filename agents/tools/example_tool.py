"""Example tool: counts words and characters of a text."""

from __future__ import annotations

import logging
from typing import Any

from agents.core.exceptions import ToolError
from agents.tools.base import BaseTool

logger = logging.getLogger(__name__)


class WordCountTool(BaseTool):
    """Returns ``{"words": int, "characters": int}`` for the given ``text``."""

    name = "word_count"
    description = "Counts the words and characters of a text."

    async def run(self, *, text: str = "", **kwargs: Any) -> dict[str, int]:
        """Count words (whitespace separated) and characters of ``text``."""
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise ToolError(f"word_count got unexpected arguments: {unexpected}", tool=self.name)
        if not isinstance(text, str):
            raise ToolError("word_count requires 'text' to be a string", tool=self.name)
        return {"words": len(text.split()), "characters": len(text)}
