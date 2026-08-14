"""The liveness contract, and the promise that the runtime surface did not change it.

No network, no credentials: the app is built in-process and driven by the Starlette test
client.

The additions at M3 are the ones a liveness probe most often loses: it must not grow
dependency state, and it must not start failing because a retrieval backend is
unreachable. A probe that reports a downstream's health makes an orchestrator restart a
healthy process, which does not fix the downstream.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_rag import __version__
from agentic_rag.api.request_id import REQUEST_ID_HEADER
from agentic_rag.main import create_app
from agentic_rag.tools.retrieve import PRODUCTION_RAG_URL_ENV


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
    assert __version__ == "1.0.0"


def test_health_stays_liveness_only_and_reports_no_dependency() -> None:
    with TestClient(create_app()) as client:
        body = client.get("/health").json()

    assert set(body) == {"status", "service", "version"}


def test_health_does_not_change_when_a_retrieval_service_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PRODUCTION_RAG_URL_ENV, "http://127.0.0.1:9")

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_carries_the_correlation_header_like_every_other_response() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health", headers={REQUEST_ID_HEADER: "probe-1"})

    assert response.headers[REQUEST_ID_HEADER] == "probe-1"
