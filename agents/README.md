# menu-hero-agents

Framework-agnostic Python agent runtime for Menu Hero. Import name: `agents`.
It knows nothing about HTTP: the FastAPI backend (`backend/`) and future queue workers
call `agents.run_agent()` / `agents.stream_agent()` and get plain pydantic results.

Runtime dependencies: `pydantic`, `pydantic-settings`. Nothing else (enforced by
`tests/test_boundaries.py`, which AST-scans every module for `fastapi`, `starlette`,
`uvicorn`, `app`, `backend`, `frontend`, `nuxt` imports).

## Layout

```
agents/                      <- this directory IS the package (pyproject lives inside it)
  __init__.py                public API re-exports, __version__
  __main__.py                CLI: python -m agents "hello" [--agent NAME] [--stream]
  core/agent.py              BaseAgent (run / stream / prepare_context / run_from_stream)
  core/context.py            AgentContext (request, run_id, memory, tools, events, metadata)
  core/events.py             AgentEvent hierarchy, parse_event(), emitters (Null/Collecting/Queue)
  core/exceptions.py         AgentError family
  core/registry.py           AgentRegistry, build_default_registry(), get_default_registry()
  core/runner.py             run_agent(), stream_agent()   <- entry points
  core/config.py             AgentSettings, get_settings()
  schemas/agent.py           AgentRequest, AgentResult, AgentInfo
  schemas/messages.py        Message
  memory/                    ConversationMemory ABC, InMemoryConversationMemory
  tools/                     BaseTool, ToolRegistry, WordCountTool ("word_count")
  integrations/llm.py        LLMClient ABC, StubLLMClient, get_llm_client()
  implementations/           ExampleAgent ("example")
  workflows/                 SequentialWorkflow, build_example_workflow() ("example_workflow")
  tests/                     pytest suite (not packaged)
```

## Setup and verification

All commands run from this directory (`cd agents`). Python 3.13 (`.python-version`), managed by uv.

```bash
uv sync                      # creates agents/.venv with the package installed editable
uv run pytest -q             # tests (pytest-asyncio auto mode)
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy .                # strict type checking (package + tests)
uv build                     # sdist + wheel in dist/ (tests/ and .venv/ are never packaged)
```

Because the package is installed editable, it imports from any working directory:

```bash
cd /tmp && /path/to/menu-hero-core/agents/.venv/bin/python -c "import agents; print(agents.__file__)"
```

## Usage

### Python

```python
import asyncio
from agents import AgentRequest, run_agent, stream_agent


async def main() -> None:
    result = await run_agent(AgentRequest(message="Hello agent"))  # agent_name="example"
    print(result.response)  # "Processed: Hello agent"
    # {"tools_used": ["word_count"], "word_count": 2, "characters": 11, "run_id": "...", "duration_ms": 0.4}
    print(result.metadata)

    async for event in stream_agent(AgentRequest(message="Hello agent")):
        print(event.type)  # agent_started, tool_started, tool_completed, agent_completed


asyncio.run(main())
```

`run_agent(request, *, agent_name="example", registry=None, timeout=None)`

- looks the agent up in the registry (`AgentNotFoundError` for unknown names),
- creates an `AgentContext` (fresh in-memory memory, default tools, `run_id`),
- applies `asyncio.timeout` (default `AgentSettings.agent_timeout_seconds`) → `AgentTimeoutError`,
- wraps any non-`AgentError` exception in `AgentExecutionError` (original chained as `__cause__`),
- merges `run_id` and `duration_ms` into `result.metadata`.

`stream_agent(request, *, agent_name="example", registry=None)` yields `AgentEvent`s. Failures
during the run are reported as a final `agent_failed` event, never raised. The `agent_completed`
event carries the same finalised result as `run_agent`.

Error mapping suggested for HTTP callers: `AgentNotFoundError` → 404 (`str(exc)` is
`Unknown agent 'x'`), `AgentTimeoutError` → 504, any other `AgentError` → 500.

### CLI

```bash
uv run python -m agents "hello"                       # AgentResult as indented JSON
uv run python -m agents "hello" --agent example_workflow
uv run python -m agents "hello" --stream              # one JSON line per event
uv run python -m agents --list                        # registered agents
uv run python -m agents "hello" --timeout 5 --log-level DEBUG
```

Exit codes: `0` success, `1` agent error (message on stderr), `2` usage error.

## Events

Every event has `type`, `run_id`, `agent`, `timestamp` (UTC). `type` is a Literal discriminator:

| type              | extra fields                         | produced by                      |
|-------------------|--------------------------------------|----------------------------------|
| `agent_started`   | `message`                            | `BaseAgent.stream`               |
| `tool_started`    | `tool`, `input`                      | `AgentContext.call_tool`         |
| `tool_completed`  | `tool`, `output`, `duration_ms`      | `AgentContext.call_tool`         |
| `token`           | `token`                              | streaming agents                 |
| `agent_completed` | `result` (`AgentResult`)             | `BaseAgent.stream`               |
| `agent_failed`    | `error`, `error_type`                | `BaseAgent.stream`               |

`agents.parse_event(json_or_dict)` parses any of them into the concrete class
(`AnyAgentEvent` is the discriminated union). Serialise with `event.model_dump_json()`; an SSE
producer writes `event: {event.type}\ndata: {event.model_dump_json()}\n\n`.

### How streaming works

`BaseAgent.stream()` is concrete: it swaps a `QueueEventEmitter` into the context (forwarding to
whatever emitter the caller supplied), runs `run()` in a task, yields `agent_started`, relays every
event the agent emits through `context.emit()` / `context.call_tool()` live, then yields
`agent_completed(result)` or `agent_failed(error, error_type)`. If the consumer stops iterating
early, the run task is cancelled. Agents that produce tokens can override `stream()` and implement
`run()` as `return await self.run_from_stream(message, context)`.

## Extending

### A new agent

```python
from agents import AgentContext, AgentResult, BaseAgent, Message, get_default_registry


class ShoutAgent(BaseAgent):
    name = "shout"
    description = "Upper-cases the message."

    async def run(self, message: str, context: AgentContext | None = None) -> AgentResult:
        context = self.prepare_context(message, context)  # works with context=None
        await context.memory.add(Message(role="user", content=message))
        counts = await context.call_tool("word_count", text=message)  # emits tool events
        return AgentResult(response=message.upper(), agent=self.agent_name, metadata=counts)


get_default_registry().register("shout", ShoutAgent, description=ShoutAgent.description)
```

Built-in agents live in `implementations/` and are registered in
`core/registry.py::build_default_registry()`.

### A new tool

Subclass `BaseTool`, set `name`, implement `async def run(self, *, ..., **kwargs)` returning
JSON-serialisable data, and add it to `tools/base.py::build_default_tool_registry()` (or register
it on the `ToolRegistry` you pass to `AgentContext.create(request, tools=...)`).

### A workflow

`SequentialWorkflow([agent_a, agent_b], name="my_workflow")` is itself an agent: the response of
each step becomes the next step's message, tool events of all steps stream live, memory is shared.

### A real LLM provider

Only `StubLLMClient` exists (`LLM_PROVIDER=stub`, the default). `get_llm_client()` raises
`LLMNotConfiguredError` for `openai` / `anthropic` / `google` until an implementation exists. To add one:

1. Add the SDK to `dependencies` in `pyproject.toml` (`uv add <sdk>`).
2. Create `agents/integrations/<provider>.py` with an `LLMClient` subclass implementing
   `async complete(messages, **options) -> LLMResponse` and
   `async def stream(messages, **options) -> AsyncIterator[str]` (an async generator), reading the
   key from `settings.llm_api_key.get_secret_value()` and the model from `settings.llm_model`.
3. Register a factory in `agents/integrations/llm.py::PROVIDER_FACTORIES`, e.g.
   `"openai": lambda settings: OpenAIClient(settings)`.
4. Set `LLM_PROVIDER=openai` and `LLM_API_KEY=...` in the repo-root `.env`.

Agents obtain a client with `get_llm_client()` and build prompts from `LLMMessage`s.

## Configuration

`AgentSettings` (pydantic-settings) reads, in priority order: environment variables, `./.env`,
then the repo-root `.env` (`agents/core/config.py` → `../../.env`). Keys not belonging to the
agents package (backend/frontend settings in the shared file) are ignored.

| variable                | default | meaning                                              |
|-------------------------|---------|------------------------------------------------------|
| `LLM_API_KEY`           | unset   | provider API key (`SecretStr`, never logged)         |
| `LLM_PROVIDER`          | `stub`  | `stub` \| `openai` \| `anthropic` \| `google`        |
| `LLM_MODEL`             | unset   | provider-specific model name                         |
| `AGENT_TIMEOUT_SECONDS` | `60`    | default wall-clock limit per run (must be > 0)       |

`get_settings()` caches one instance per process; `reset_settings()` clears it (tests).
`settings.llm_configured` is true only when a non-stub provider has an API key.

## Logging

The package logs under the `agents` logger hierarchy and installs a `NullHandler`; the host
application configures handlers. Secrets are never logged.
