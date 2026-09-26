"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agents.core.config import reset_settings
from agents.core.context import AgentContext
from agents.core.events import CollectingEventEmitter
from agents.core.registry import AgentRegistry, build_default_registry, reset_default_registry
from agents.schemas.agent import AgentRequest


@pytest.fixture(autouse=True)
def _isolate_process_caches() -> Iterator[None]:
    """Make sure cached settings/registry never leak between tests."""
    reset_settings()
    reset_default_registry()
    yield
    reset_settings()
    reset_default_registry()


@pytest.fixture
def registry() -> AgentRegistry:
    return build_default_registry()


@pytest.fixture
def collector() -> CollectingEventEmitter:
    return CollectingEventEmitter()


@pytest.fixture
def context(collector: CollectingEventEmitter) -> AgentContext:
    return AgentContext.create(AgentRequest(message="hello"), events=collector)
