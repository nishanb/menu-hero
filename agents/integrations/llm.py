"""Language-model client abstraction.

Only the deterministic :class:`StubLLMClient` exists today. A real provider plugs in by
adding a module such as ``agents/integrations/openai.py`` with an :class:`LLMClient`
subclass and registering its factory in :data:`PROVIDER_FACTORIES` below.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.core.config import AgentSettings, get_settings
from agents.core.exceptions import LLMNotConfiguredError

logger = logging.getLogger(__name__)


class LLMMessage(BaseModel):
    """A chat message sent to a model."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str


class LLMResponse(BaseModel):
    """A model completion."""

    model_config = ConfigDict(extra="forbid")

    content: str
    model: str = "stub"
    usage: dict[str, int] = Field(default_factory=dict)


class LLMClient(ABC):
    """Async interface every provider implements."""

    provider: ClassVar[str] = "base"

    @abstractmethod
    async def complete(self, messages: Sequence[LLMMessage], **options: Any) -> LLMResponse:
        """Return a full completion for ``messages``."""

    @abstractmethod
    def stream(self, messages: Sequence[LLMMessage], **options: Any) -> AsyncIterator[str]:
        """Yield the completion for ``messages`` incrementally (token/chunk strings)."""


def _last_user_content(messages: Sequence[LLMMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return messages[-1].content if messages else ""


class StubLLMClient(LLMClient):
    """Deterministic offline client: answers ``"stub: <last user message>"``."""

    provider = "stub"

    def __init__(self, model: str = "stub") -> None:
        self.model = model

    async def complete(self, messages: Sequence[LLMMessage], **options: Any) -> LLMResponse:
        """Echo the last user message behind a ``stub:`` prefix."""
        content = f"stub: {_last_user_content(messages)}"
        return LLMResponse(
            content=content,
            model=self.model,
            usage={"prompt_tokens": sum(len(m.content.split()) for m in messages)},
        )

    async def stream(self, messages: Sequence[LLMMessage], **options: Any) -> AsyncIterator[str]:
        """Yield the completion word by word; joining the chunks reproduces ``complete()``."""
        response = await self.complete(messages, **options)
        for index, word in enumerate(response.content.split(" ")):
            yield word if index == 0 else f" {word}"


ProviderFactory = Callable[[AgentSettings], LLMClient]

PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
    "stub": lambda settings: StubLLMClient(model=settings.llm_model or "stub"),
}
"""Provider name → factory. Register real providers here (see module docstring)."""


def get_llm_client(settings: AgentSettings | None = None) -> LLMClient:
    """Build the client for ``settings.llm_provider`` (defaults to :func:`get_settings`).

    Raises :class:`LLMNotConfiguredError` when the provider has no implementation yet or
    when a real provider is selected without ``LLM_API_KEY``.
    """
    settings = settings if settings is not None else get_settings()
    provider = settings.llm_provider
    factory = PROVIDER_FACTORIES.get(provider)
    if factory is None:
        raise LLMNotConfiguredError(
            f"LLM provider '{provider}' is not implemented. Add an LLMClient subclass in "
            f"agents/integrations/{provider}.py and register it in "
            "agents.integrations.llm.PROVIDER_FACTORIES.",
            provider=provider,
        )
    if provider != "stub" and not settings.llm_configured:
        raise LLMNotConfiguredError(
            f"LLM provider '{provider}' requires LLM_API_KEY to be set.", provider=provider
        )
    client = factory(settings)
    logger.debug("llm client created: provider=%s", provider)
    return client
