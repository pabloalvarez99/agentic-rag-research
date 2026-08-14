"""The browser surface exercises the same free research service as the JSON API."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentic_rag.api.request_id import REQUEST_ID_HEADER
from agentic_rag.api.service import ResearchService
from agentic_rag.main import create_app
from agentic_rag.tools.base import ToolError

from .conftest import ANSWERABLE, RecordingFactory, StubRunner


@pytest.fixture
def client(offline_service: ResearchService) -> Iterator[TestClient]:
    """Serve the UI over a service that cannot reach a network."""
    with TestClient(create_app(offline_service)) as running:
        yield running


def test_home_is_an_accessible_free_demo(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'label for="question"' in response.text
    assert 'label for="max_steps"' in response.text
    assert "Demo mode (free / deterministic)" in response.text
    assert "OpenAI" not in response.text
    assert 'href="/compare"' in response.text


def test_compare_page_loads_two_file_inputs(client: TestClient) -> None:
    response = client.get("/compare")

    assert response.status_code == 200
    assert 'id="compare-form"' in response.text
    assert 'id="left-file"' in response.text
    assert 'id="right-file"' in response.text
    assert "No server id lookup" in response.text
    assert "/v1/runs/compare" in response.text


def test_submit_renders_the_whole_inspectable_run(client: TestClient) -> None:
    response = client.post(
        "/ui/research",
        data={"question": ANSWERABLE, "max_steps": "4"},
        headers={REQUEST_ID_HEADER: "ui-run-42"},
    )

    assert response.status_code == 200
    for visible in [
        "Report",
        "Citations",
        "Status",
        "Steps used",
        "Request ID",
        "ui-run-42",
        "Trace timeline",
        "tool call",
        "stop",
    ]:
        assert visible in response.text


def test_invalid_form_value_renders_a_typed_error_page(client: TestClient) -> None:
    response = client.post(
        "/ui/research",
        data={"question": ANSWERABLE, "max_steps": "999"},
    )

    assert response.status_code == 422
    assert "Validation Error" in response.text
    assert "validation_error" in response.text
    assert "Request ID" in response.text


def test_backend_failure_renders_a_typed_error_page_without_leaking_details() -> None:
    leaked = "http://user:password@example.invalid/v1/query failed"
    service = ResearchService(
        runner=StubRunner(error=ToolError(leaked)),
        retriever_factory=RecordingFactory(),
    )

    with TestClient(create_app(service)) as client:
        response = client.post(
            "/ui/research",
            data={"question": ANSWERABLE, "max_steps": "4"},
        )

    assert response.status_code == 503
    assert "Backend Unavailable" in response.text
    assert "backend_unavailable" in response.text
    assert leaked not in response.text


def test_ui_assets_reference_no_external_origin() -> None:
    for root in [Path("src/agentic_rag/templates"), Path("src/agentic_rag/static")]:
        for path in root.rglob("*"):
            if path.is_file():
                contents = path.read_text(encoding="utf-8")
                assert "http://" not in contents
                assert "https://" not in contents
