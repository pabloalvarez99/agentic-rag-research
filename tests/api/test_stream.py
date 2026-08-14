"""Server-sent events stream the same run a POST would return, as it happens."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from agentic_rag.api.request_id import REQUEST_ID_HEADER
from agentic_rag.api.runs import RUNS_PATH
from agentic_rag.api.service import ResearchService
from agentic_rag.api.stream import STREAM_PATH, encode_event, stop_reason_of
from agentic_rag.main import create_app
from agentic_rag.tools.base import ToolError

from .conftest import ANSWERABLE, OFF_CORPUS, RecordingFactory, StubRunner, build_state


@pytest.fixture
def client(offline_service: ResearchService) -> Iterator[TestClient]:
    """Serve the stream over a service that cannot reach a network."""
    with TestClient(create_app(offline_service)) as running:
        yield running


def _parse_sse(body: str) -> list[tuple[str, dict[object, object]]]:
    """Return ``(event_name, payload)`` pairs from an SSE body."""
    events: list[tuple[str, dict[object, object]]] = []
    name = "message"
    data_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("event:"):
            name = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
        elif line == "" and data_lines:
            payload = json.loads("\n".join(data_lines))
            events.append((name, payload))
            name = "message"
            data_lines = []
    if data_lines:
        payload = json.loads("\n".join(data_lines))
        events.append((name, payload))
    return events


def test_encode_event_is_a_named_sse_frame() -> None:
    frame = encode_event("trace", {"offset": 0, "event": "plan_created"})

    assert frame.startswith("event: trace\n")
    assert 'data: {"offset":0,"event":"plan_created"}' in frame
    assert frame.endswith("\n\n")


def test_the_stream_emits_every_trace_event_then_done(client: TestClient) -> None:
    response = client.get(
        STREAM_PATH,
        params={"question": ANSWERABLE, "max_steps": 4, "retriever": "fake"},
        headers={REQUEST_ID_HEADER: "stream-1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers[REQUEST_ID_HEADER] == "stream-1"

    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "trace"
    assert names[-1] == "done"
    assert "error" not in names

    traces = [payload for name, payload in events if name == "trace"]
    assert traces[0]["event"] == "plan_created"
    assert traces[-1]["event"] == "stop"
    assert [payload["offset"] for payload in traces] == list(range(len(traces)))

    done = events[-1][1]
    assert done["request_id"] == "stream-1"
    assert done["status"] in {"done", "refused", "budget_exhausted", "degraded"}
    assert done["stop_reason"] in {
        "evidence_sufficient",
        "no_evidence",
        "insufficient_evidence",
        "budget_spent",
    }
    assert done["run"] == f"{RUNS_PATH}/stream-1"
    assert isinstance(done["steps_used"], int)


def test_a_streamed_run_is_fetchable_afterwards(client: TestClient) -> None:
    streamed = client.get(
        STREAM_PATH,
        params={"question": OFF_CORPUS, "max_steps": 3},
        headers={REQUEST_ID_HEADER: "stream-refused"},
    )
    events = _parse_sse(streamed.text)
    done = events[-1][1]
    assert done["status"] == "refused"

    stored = client.get(f"{RUNS_PATH}/stream-refused")
    assert stored.status_code == 200
    assert stored.json()["status"] == "refused"
    assert stored.json()["stop_reason"] == done["stop_reason"]
    traces = [payload for name, payload in events if name == "trace"]
    assert stored.json()["trace"] == traces


def test_stream_validation_failures_are_status_codes_not_events(client: TestClient) -> None:
    response = client.get(STREAM_PATH, params={"question": ANSWERABLE, "max_steps": 999})

    assert response.status_code == 422
    assert response.json()["error_type"] == "validation_error"


def test_a_backend_failure_is_an_error_event_with_the_shared_envelope() -> None:
    leaked = "http://user:password@example.invalid/v1/query failed"
    service = ResearchService(
        runner=StubRunner(error=ToolError(leaked)),
        retriever_factory=RecordingFactory(),
    )

    with TestClient(create_app(service)) as client:
        response = client.get(
            STREAM_PATH,
            params={"question": ANSWERABLE, "max_steps": 4},
            headers={REQUEST_ID_HEADER: "stream-fail"},
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    envelope = events[-1][1]
    assert envelope["error_type"] == "backend_unavailable"
    assert envelope["request_id"] == "stream-fail"
    assert leaked not in response.text


def test_stop_reason_of_reads_the_terminal_event() -> None:
    state = build_state()
    assert stop_reason_of(list(state.trace)) == "evidence_sufficient"
    assert stop_reason_of([]) is None


def test_the_stream_route_is_documented() -> None:
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()

    assert STREAM_PATH in schema["paths"]
    assert "get" in schema["paths"][STREAM_PATH]
