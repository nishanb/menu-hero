"""LLM client abstraction and stub."""

from __future__ import annotations

import pytest

from agents.core.config import AgentSettings
from agents.core.exceptions import LLMNotConfiguredError
from agents.integrations.llm import LLMClient, LLMMessage, StubLLMClient, get_llm_client


def test_llm_client_is_abstract() -> None:
    with pytest.raises(TypeError):
        LLMClient()  # type: ignore[abstract]


async def test_stub_complete_echoes_last_user_message() -> None:
    client = StubLLMClient()
    messages = [
        LLMMessage(role="system", content="be nice"),
        LLMMessage(role="user", content="hello world"),
        LLMMessage(role="assistant", content="ignored"),
    ]
    response = await client.complete(messages)
    assert response.content == "stub: hello world"
    assert response.model == "stub"
    assert response.usage["prompt_tokens"] == 5
    assert (await client.complete([])).content == "stub: "


async def test_stub_stream_yields_words_that_join_to_the_completion() -> None:
    client = StubLLMClient(model="stub-1")
    messages = [LLMMessage(role="user", content="hello big world")]
    chunks = [chunk async for chunk in client.stream(messages)]
    assert chunks == ["stub:", " hello", " big", " world"]
    assert "".join(chunks) == (await client.complete(messages)).content


def test_get_llm_client_stub_from_settings() -> None:
    settings = AgentSettings.model_validate({"llm_provider": "stub", "llm_model": "m"})
    client = get_llm_client(settings)
    assert isinstance(client, StubLLMClient)
    assert client.model == "m"


def test_get_llm_client_uses_process_settings_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    assert isinstance(get_llm_client(), StubLLMClient)


@pytest.mark.parametrize("provider", ["openai", "anthropic", "google"])
def test_get_llm_client_unimplemented_provider(provider: str) -> None:
    settings = AgentSettings.model_validate({"llm_provider": provider, "llm_api_key": "sk-test"})
    with pytest.raises(LLMNotConfiguredError) as excinfo:
        get_llm_client(settings)
    assert f"agents/integrations/{provider}.py" in str(excinfo.value)
    assert excinfo.value.provider == provider
