"""Menu Hero agents: a framework-agnostic agent runtime (no FastAPI, no HTTP).

Public API is re-exported here; ``run_agent``/``stream_agent`` are the entry points used by
the HTTP layer and background workers.
"""

from __future__ import annotations

import logging

from agents.core.agent import BaseAgent
from agents.core.config import AgentSettings, get_settings, reset_settings
from agents.core.context import AgentContext
from agents.core.events import (
    AgentCompleted,
    AgentEvent,
    AgentFailed,
    AgentStarted,
    AnyAgentEvent,
    CollectingEventEmitter,
    EventEmitter,
    NullEventEmitter,
    QueueEventEmitter,
    TokenStream,
    ToolCompleted,
    ToolStarted,
    parse_event,
)
from agents.core.exceptions import (
    AgentError,
    AgentExecutionError,
    AgentNotFoundError,
    AgentTimeoutError,
    LLMError,
    LLMNotConfiguredError,
    ToolError,
    ToolNotFoundError,
)
from agents.core.registry import (
    AgentFactory,
    AgentRegistry,
    build_default_registry,
    get_default_registry,
    reset_default_registry,
)
from agents.core.runner import run_agent, stream_agent
from agents.implementations.example_agent import ExampleAgent
from agents.integrations.llm import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    StubLLMClient,
    get_llm_client,
)
from agents.memory.base import ConversationMemory
from agents.memory.conversation import InMemoryConversationMemory
from agents.schemas.agent import AgentInfo, AgentRequest, AgentResult
from agents.schemas.messages import Message
from agents.tools.base import BaseTool, ToolRegistry, build_default_tool_registry
from agents.tools.example_tool import WordCountTool
from agents.workflows.base import SequentialWorkflow
from agents.workflows.example_workflow import build_example_workflow

__version__ = "0.1.0"

# Library convention: never configure logging for the host application.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "AgentCompleted",
    "AgentContext",
    "AgentError",
    "AgentEvent",
    "AgentExecutionError",
    "AgentFactory",
    "AgentFailed",
    "AgentInfo",
    "AgentNotFoundError",
    "AgentRegistry",
    "AgentRequest",
    "AgentResult",
    "AgentSettings",
    "AgentStarted",
    "AgentTimeoutError",
    "AnyAgentEvent",
    "BaseAgent",
    "BaseTool",
    "CollectingEventEmitter",
    "ConversationMemory",
    "EventEmitter",
    "ExampleAgent",
    "InMemoryConversationMemory",
    "LLMClient",
    "LLMError",
    "LLMMessage",
    "LLMNotConfiguredError",
    "LLMResponse",
    "Message",
    "NullEventEmitter",
    "QueueEventEmitter",
    "SequentialWorkflow",
    "StubLLMClient",
    "TokenStream",
    "ToolCompleted",
    "ToolError",
    "ToolNotFoundError",
    "ToolRegistry",
    "ToolStarted",
    "WordCountTool",
    "__version__",
    "build_default_registry",
    "build_default_tool_registry",
    "build_example_workflow",
    "get_default_registry",
    "get_llm_client",
    "get_settings",
    "parse_event",
    "reset_default_registry",
    "reset_settings",
    "run_agent",
    "stream_agent",
]
