"""GET /api/health."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_exact_body(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_not_served_at_root(client: TestClient) -> None:
    assert client.get("/health").status_code == 404


def test_docs_live_under_api_prefix(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 200
    openapi = client.get("/api/openapi.json")
    assert openapi.status_code == 200
    assert "/api/agents/run" in openapi.json()["paths"]
