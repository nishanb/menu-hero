"""AgentSettings."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.core.config import REPO_ROOT_ENV_FILE, AgentSettings, get_settings, reset_settings


def test_defaults() -> None:
    settings = AgentSettings.model_validate({})
    assert settings.llm_provider == "stub"
    assert settings.llm_api_key is None
    assert settings.llm_model is None
    assert settings.agent_timeout_seconds == 60
    assert settings.llm_configured is False


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-secret")
    monkeypatch.setenv("LLM_MODEL", "gpt-x")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "5.5")
    settings = AgentSettings()
    assert settings.llm_provider == "openai"
    assert settings.llm_model == "gpt-x"
    assert settings.agent_timeout_seconds == 5.5
    assert settings.llm_configured is True
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "sk-secret"
    assert "sk-secret" not in repr(settings)


def test_real_provider_without_key_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    settings = AgentSettings.model_validate({"llm_provider": "anthropic"})
    assert settings.llm_configured is False


def test_invalid_values_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentSettings.model_validate({"llm_provider": "nope"})
    with pytest.raises(ValidationError):
        AgentSettings.model_validate({"agent_timeout_seconds": 0})


def test_unknown_env_keys_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SECRET_KEY", "irrelevant")
    AgentSettings()


def test_repo_root_env_file_location() -> None:
    assert REPO_ROOT_ENV_FILE.name == ".env"
    assert REPO_ROOT_ENV_FILE.parent == Path(__file__).resolve().parents[2]
    assert ".env" in [str(path) for path in AgentSettings.model_config["env_file"]]  # type: ignore[union-attr]


def test_get_settings_is_cached_until_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "7")
    first = get_settings()
    assert first.agent_timeout_seconds == 7
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "8")
    assert get_settings() is first
    reset_settings()
    assert get_settings().agent_timeout_seconds == 8
