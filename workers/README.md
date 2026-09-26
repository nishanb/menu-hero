# workers/ — background agent execution (reserved)

Nothing runs here yet. `workers/__init__.py` is a placeholder so the directory
exists in the tree; this document records the architecture the rest of the
monorepo is already shaped for, so that adding workers later is an addition,
not a refactor.

## Why a worker tier

Today an agent run is synchronous inside the HTTP request:

```
HTTP -> app/api/routes/agents.py -> AgentService -> InProcessAgentExecutor -> agents.run_agent()
```

That is the right shape for an app with short agent runs and a single
container. It stops being right when runs take minutes, need retries, must
survive a deploy, or should not compete with request handling for CPU. The
target shape is:

```
HTTP -> route -> AgentService -> QueueAgentExecutor -> [queue] -> worker -> agents.run_agent()
                                                                       |
                                                    result / events -> [store] -> HTTP (poll or SSE)
```

## The swap point: `AgentExecutor`

`backend/app/services/agent_service.py` defines the `AgentExecutor` protocol
and one implementation, `InProcessAgentExecutor`. Routes never touch agents
directly; they depend on `AgentService` via `app/dependencies/agents.py`, and
`AgentService` depends on an `AgentExecutor`. Moving execution off the web
process therefore means:

1. Add a `QueueAgentExecutor` that enqueues an `agents.schemas.AgentRequest`
   (plus the agent name) and either waits for the result (request/response over
   the queue) or returns a job id for the client to poll.
2. Wire it in `app/dependencies/agents.py` behind a setting (for example
   `AGENT_EXECUTOR=inprocess|queue`).
3. Nothing in `app/api/`, `app/schemas/` or `agents/` changes.

## What a worker is

`workers/` will become a small, separate Python package with its own
`pyproject.toml`, depending on `../agents` exactly like the backend does:

```toml
[project]
name = "menu-hero-workers"
dependencies = ["menu-hero-agents", "<queue client>"]

[tool.uv.sources]
menu-hero-agents = { path = "../agents", editable = true }
```

Its loop is deliberately boring:

```
receive job -> AgentRequest.model_validate(payload)
            -> await agents.run_agent(request, agent_name=job.agent, timeout=...)
            -> publish AgentResult (and optionally the AgentEvent stream via a
               QueueEventEmitter) -> ack the message
```

It reuses `agents.core.runner.run_agent` / `stream_agent`, the same registry
(`agents.core.registry.get_default_registry`) and the same exception
hierarchy (`AgentNotFoundError`, `AgentTimeoutError`, ...), so behaviour is
identical whether a run happens in the web process or in a worker.

Packaging the worker follows the backend recipe in the root `Dockerfile`: a
`uv sync --frozen --no-dev --no-editable` build stage with `agents/` and
`workers/` side by side, then a slim runtime stage whose `CMD` is the worker
loop. On Elastic Beanstalk it would be a separate *worker tier* environment
(SQS-backed) or a second container/process in this environment.

## Candidate queues

| Option | Fits when | Notes |
|--------|-----------|-------|
| **Amazon SQS** | Already on AWS (this repo deploys to Elastic Beanstalk) | EB has a native worker tier that polls SQS and POSTs to the worker; zero servers to run. At-least-once delivery: make runs idempotent by `run_id`. |
| **Redis** (Streams / RQ / arq) | Need sub-second latency or pub/sub for streaming events back | arq is async-native and pairs well with `stream_agent`; needs ElastiCache or a Redis container. |
| **MongoDB-backed** (`findOneAndUpdate` on a status field, optionally a capped collection or change streams for wake-ups) | A database is already provisioned and volumes are modest | One less moving part; `DATABASE_URL` is already plumbed through the backend settings. MongoDB has no `SKIP LOCKED`, so a claim is a single atomic `find_one_and_update({"status": "pending"}, {"$set": {"status": "running", "worker_id": ..., "claimed_at": ...}})`; add a lease and a heartbeat so a crashed worker's job returns to `pending`. Change streams need a replica set — plain polling works on a standalone server. |

Pick the one that matches the deployment you actually have; the code above
does not care which.

## Invariants

- **`agents/` never learns about the queue.** It stays a pure library with
  `pydantic` and `pydantic-settings` as its only runtime dependencies, enforced
  by `agents/tests/test_boundaries.py`. Queue clients, brokers and job models
  live in `workers/` and `backend/`, never in `agents/`.
- **`run_agent` is the only entry point.** Workers call
  `agents.run_agent()` / `agents.stream_agent()`; they do not instantiate
  agents or reach into `AgentContext` themselves.
- **Payloads are the public schemas.** What goes over the wire is
  `agents.schemas.AgentRequest` in and `AgentResult` / `AgentEvent` out
  (`model_dump(mode="json")` / `model_validate`). No pickling of live objects.
- **Secrets stay server-side.** `LLM_*` variables are read by the agents
  package in whichever process runs it; the browser only ever sees `/api/*`.
- **Timeouts are enforced by the runner.** `run_agent(timeout=...)` (default
  `AGENT_TIMEOUT_SECONDS`) is the single timeout; the queue's visibility
  timeout must be longer than it.
