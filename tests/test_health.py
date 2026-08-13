"""The liveness contract, which the scaffold is allowed to have opinions about.

No network, no credentials: the app is built in-process and driven by the
Starlette test client.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from agentic_rag import __version__
from agentic_rag.main import create_app


def test_health_reports_service_and_version() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "agentic-rag-research",
        "version": __version__,
    }


def test_health_is_documented_in_the_openapi_schema() -> None:
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()

    assert "/health" in schema["paths"]
    assert schema["info"]["version"] == __version__


def test_version_is_the_scaffold_version() -> None:
    assert __version__ == "0.1.0"
