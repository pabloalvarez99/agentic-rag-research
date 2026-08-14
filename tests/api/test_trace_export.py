"""The trace can leave the service, through the API and through the browser.

Everything here runs against the in-process fake retriever. No test opens a socket to
anything but the test client, and none of them reads a credential.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from agentic_rag.api.request_id import REQUEST_ID_HEADER
from agentic_rag.api.routes import RESEARCH_PATH, TRACE_PATH, trace_filename
from agentic_rag.api.service import ResearchService
from agentic_rag.api.ui import TRACE_DOWNLOAD_PATH
from agentic_rag.main import create_app
from agentic_rag.tools.base import ToolError

from .conftest import ANSWERABLE, RecordingFactory, StubRunner, build_state


@pytest.fixture
def client(offline_service: ResearchService) -> Iterator[TestClient]:
    """Serve the export over a service that cannot reach a network."""
    with TestClient(create_app(offline_service)) as running:
        yield running


def test_the_api_export_is_the_events_the_run_recorded() -> None:
    # The runner returns a state built here, so the downloaded file is compared against
    # the in-memory events rather than against another copy of the same serialiser.
    state = build_state(steps=2)
    service = ResearchService(runner=StubRunner(state=state), retriever_factory=RecordingFactory())

    with TestClient(create_app(service)) as client:
        response = client.post(TRACE_PATH, json={"question": ANSWERABLE, "max_steps": 4})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == [event.model_dump(mode="json") for event in state.trace]


def test_the_api_export_matches_the_trace_the_research_route_returns(client: TestClient) -> None:
    body = {"question": ANSWERABLE, "max_steps": 4}

    run = client.post(RESEARCH_PATH, json=body)
    exported = client.post(TRACE_PATH, json=body)

    assert run.status_code == 200
    assert exported.status_code == 200
    assert exported.json() == run.json()["trace"]


def test_the_export_ends_in_a_stop_event(client: TestClient) -> None:
    events = client.post(TRACE_PATH, json={"question": ANSWERABLE, "max_steps": 4}).json()

    assert events
    assert events[0]["event"] == "plan_created"
    assert events[-1]["event"] == "stop"


def test_the_export_is_offered_as_a_named_download(client: TestClient) -> None:
    response = client.post(
        TRACE_PATH,
        json={"question": ANSWERABLE, "max_steps": 4},
        headers={REQUEST_ID_HEADER: "export-42"},
    )

    assert response.headers[REQUEST_ID_HEADER] == "export-42"
    assert response.headers["content-disposition"] == 'attachment; filename="trace-export-42.json"'


@pytest.mark.parametrize(
    ("request_id", "expected"),
    [
        ("export-42", "trace-export-42.json"),
        ('a"b/c', "trace-abc.json"),
        ("", "trace-export.json"),
    ],
)
def test_the_filename_cannot_carry_a_quote_or_a_separator(request_id: str, expected: str) -> None:
    # The id can be echoed from the caller, so it reaches a header and a filename.
    assert trace_filename(request_id) == expected


def test_the_export_refuses_the_same_requests_the_research_route_refuses(
    client: TestClient,
) -> None:
    response = client.post(TRACE_PATH, json={"question": ANSWERABLE, "max_steps": 999})

    assert response.status_code == 422
    assert response.json()["error_type"] == "validation_error"


def test_a_backend_failure_exports_nothing_and_says_so_without_leaking() -> None:
    leaked = "http://user:password@example.invalid/v1/query failed"
    service = ResearchService(
        runner=StubRunner(error=ToolError(leaked)),
        retriever_factory=RecordingFactory(),
    )

    with TestClient(create_app(service)) as client:
        response = client.post(TRACE_PATH, json={"question": ANSWERABLE, "max_steps": 4})

    assert response.status_code == 503
    assert response.json()["error_type"] == "backend_unavailable"
    assert leaked not in response.text


def test_the_result_page_offers_the_stored_run_download(client: TestClient) -> None:
    page = client.post(
        "/ui/research",
        data={"question": ANSWERABLE, "max_steps": "4"},
        headers={REQUEST_ID_HEADER: "ui-download"},
    )

    assert page.status_code == 200
    assert "Download stored trace (JSON)" in page.text
    assert 'href="/v1/runs/ui-download/trace.json"' in page.text


def test_the_browser_download_is_the_trace_the_page_stored(client: TestClient) -> None:
    page = client.post(
        "/ui/research",
        data={"question": ANSWERABLE, "max_steps": "4"},
        headers={REQUEST_ID_HEADER: "ui-stored"},
    )
    assert page.status_code == 200

    downloaded = client.get("/v1/runs/ui-stored/trace.json")
    through_the_api = client.get("/v1/runs/ui-stored")

    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/json")
    assert "attachment; filename=" in downloaded.headers["content-disposition"]
    assert json.loads(downloaded.text) == through_the_api.json()["trace"]


def test_the_legacy_form_download_still_answers_a_bad_form_with_the_shared_envelope(
    client: TestClient,
) -> None:
    # Kept for no-JS clients; a rendered HTML error saved as .json is worse than a typed error.
    response = client.post(TRACE_DOWNLOAD_PATH, data={"question": "", "max_steps": "4"})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error_type"] == "validation_error"


def test_the_export_is_documented_as_a_route_of_its_own() -> None:
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()

    assert TRACE_PATH in schema["paths"]
    assert "post" in schema["paths"][TRACE_PATH]
    # The browser form is a UI affordance, not part of the contract a client codes to.
    assert TRACE_DOWNLOAD_PATH not in schema["paths"]
