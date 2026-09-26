"""Tool abstraction and registry."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, ClassVar

from agents.core.exceptions import ToolNotFoundError

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """A callable capability exposed to agents.

    Subclasses set ``name``/``description`` and implement :meth:`run`. Keyword arguments
    should be JSON-serialisable because they are echoed in ``ToolStarted`` events.
    """

    name: ClassVar[str] = "base"
    description: ClassVar[str] = ""

    @abstractmethod
    async def run(self, **kwargs: Any) -> Any:
        """Execute the tool and return a JSON-serialisable result."""


class ToolRegistry:
    """Name → tool lookup table."""

    def __init__(self, tools: Iterable[BaseTool] = ()) -> None:
        self._tools: dict[str, BaseTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        """Add ``tool`` under its ``name``; raises ``ValueError`` on duplicates."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool
        logger.debug("registered tool %s", tool.name)

    def get(self, name: str) -> BaseTool:
        """Return the tool registered as ``name`` or raise :class:`ToolNotFoundError`."""
        try:
            return self._tools[name]
        except KeyError:
            raise ToolNotFoundError(name) from None

    def names(self) -> list[str]:
        """Registered tool names in registration order."""
        return list(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


def build_default_tool_registry() -> ToolRegistry:
    """Registry with the built-in tools (currently only ``word_count``)."""
    from agents.tools.example_tool import WordCountTool

    return ToolRegistry([WordCountTool()])
