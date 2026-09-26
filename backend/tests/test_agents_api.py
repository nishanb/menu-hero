"""HTTP behaviour of the agent endpoints (real in-process executor + failure mapping)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import agents
import pytest
from agents import AgentEvent, AgentExecutionError, AgentTimeoutError
from fastapi.testclient import TestClient

from app.dependencies.agents import get_agent_service
from app.main import create_app
from app.services.agent_service import AgentService


def test_run_example_agent(client: TestClient) -> None:
    response = client.post("/api/agents/run", json={"message": "Hello agent"})
    assert response.status_code == 200
    body = response.json()
    assert body["response"] == "Processed: Hello agent"
    assert body["agent"] == "example"
    assert isinstance(body["metadata"], dict)
    assert "run_id" in body["metadata"]
    assert body["metadata"]["tools_used"] == ["word_count"]
    assert body["metadata"]["word_count"] == 2


def test_run_example_workflow(client: TestClient) -> None:
    response = client.post("/api/agents/run", json={"message": "hi", "agent": "example_workflow"})
    assert response.status_code == 200
    assert response.json()["response"] == "Processed: Processed: hi"
    assert response.json()["agent"] == "example_workflow"


def test_run_unknown_agent_is_404(client: TestClient) -> None:
    response = client.post("/api/agents/run", json={"message": "hi", "agent": "nope"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown agent 'nope'"}


def test_run_empty_message_is_422(client: TestClient) -> None:
    assert client.post("/api/agents/run", json={"message": ""}).status_code == 422


def test_run_missing_body_is_422(client: TestClient) -> None:
    assert client.post("/api/agents/run").status_code == 422


def test_run_invalid_agent_name_is_422(client: TestClient) -> None:
    response = client.post("/api/agents/run", json={"message": "hi", "agent": "Not Valid!"})
    assert response.status_code == 422


def test_run_message_too_long_is_422(client: TestClient) -> None:
    response = client.post("/api/agents/run", json={"message": "x" * 10_001})
    assert response.status_code == 422


def test_list_agents(client: TestClient) -> None:
    response = client.get("/api/agents")
    assert response.status_code == 200
    entries = response.json()["agents"]
    names = [entry["name"] for entry in entries]
    assert "example" in names
    assert "example_workflow" in names
    example = next(entry for entry in entries if entry["name"] == "example")
    assert example["description"] == agents.ExampleAgent.description


def test_stream_example_agent(client: TestClient) -> None:
    response = client.post("/api/agents/stream", json={"message": "hi"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    body = response.text
    positions = [body.index(f"event: {name}") for name in ("agent_started", "tool_started")]
    positions.append(body.index("event: agent_completed"))
    assert positions == sorted(positions)
    assert "event: tool_completed" in body

    messages = [chunk for chunk in body.split("\n\n") if chunk]
    assert all(chunk.startswith("event: ") and "\ndata: " in chunk for chunk in messages)
    last = agents.parse_event(messages[-1].split("\ndata: ", 1)[1])
    assert isinstance(last, agents.AgentCompleted)
    assert last.result.response == "Processed: hi"
    assert "run_id" in last.result.metadata


def test_stream_unknown_agent_is_404(client: TestClient) -> None:
    response = client.post("/api/agents/stream", json={"message": "hi", "agent": "nope"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown agent 'nope'"}


class _FailingExecutor:
    """Executor whose every call raises ``error`` (drives the exception handlers)."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def execute(self, agent_name: str, request: agents.AgentRequest) -> agents.AgentResult:
        raise self.error

    def stream(self, agent_name: str, request: agents.AgentRequest) -> AsyncIterator[AgentEvent]:
        return self._events()

    async def _events(self) -> AsyncIterator[AgentEvent]:
        yield agents.AgentStarted(run_id="r1", agent="example", message="hi")
        raise self.error

    def list_agents(self) -> list[agents.AgentInfo]:
        return []


def _client_with_executor(error: Exception) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_agent_service] = lambda: AgentService(_FailingExecutor(error))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def timeout_client() -> Iterator[TestClient]:
    yield from _client_with_executor(AgentTimeoutError("slow", agent="example", timeout=1))


@pytest.fixture
def failing_client() -> Iterator[TestClient]:
    yield from _client_with_executor(AgentExecutionError("boom: secret internals"))


def test_timeout_maps_to_504(timeout_client: TestClient) -> None:
    response = timeout_client.post("/api/agents/run", json={"message": "hi"})
    assert response.status_code == 504
    assert response.json() == {"detail": "Agent timed out"}


def test_execution_error_maps_to_500_without_internals(failing_client: TestClient) -> None:
    response = failing_client.post("/api/agents/run", json={"message": "hi"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Agent execution failed"}
    assert "secret" not in response.text


def test_stream_error_after_start_ends_with_error_event(failing_client: TestClient) -> None:
    response = failing_client.post("/api/agents/stream", json={"message": "hi"})
    assert response.status_code == 200
    assert "event: agent_started" in response.text
    assert response.text.endswith('event: error\ndata: {"detail": "Agent execution failed"}\n\n')
    assert "secret" not in response.text


def test_stream_timeout_after_start_ends_with_error_event(timeout_client: TestClient) -> None:
    response = timeout_client.post("/api/agents/stream", json={"message": "hi"})
    assert response.status_code == 200
    assert response.text.endswith('event: error\ndata: {"detail": "Agent timed out"}\n\n')


def test_cors_headers_for_configured_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,https://menuhero.example")
    with TestClient(create_app()) as cors_client:
        response = cors_client.options(
            "/api/agents/run",
            headers={
                "Origin": "https://menuhero.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://menuhero.example"
        assert response.headers["access-control-allow-credentials"] == "true"

        denied = cors_client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in denied.headers
