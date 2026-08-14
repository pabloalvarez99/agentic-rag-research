"""Finished runs are stored, fetchable, and downloadable by correlation id.

Everything here runs against the in-process fake retriever. The store is the contract
under test; no socket leaves the process.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from agentic_rag.api.request_id import REQUEST_ID_HEADER
from agentic_rag.api.routes import RESEARCH_PATH
from agentic_rag.api.runs import DEFAULT_RUN_CAPACITY, RUNS_PATH, RunArtifact, RunStore
from agentic_rag.api.schemas import ResearchRequest
from agentic_rag.api.service import ResearchService
from agentic_rag.main import create_app

from .conftest import ANSWERABLE, OFF_CORPUS, RecordingFactory, StubRunner, build_state


@pytest.fixture
def client(offline_service: ResearchService) -> Iterator[TestClient]:
    """Serve the run store over a service that cannot reach a network."""
    with TestClient(create_app(offline_service)) as running:
        yield running


def test_a_finished_run_is_fetchable_by_the_id_it_was_served_under(client: TestClient) -> None:
    run = client.post(
        RESEARCH_PATH,
        json={"question": ANSWERABLE, "max_steps": 4},
        headers={REQUEST_ID_HEADER: "run-alpha"},
    )
    assert run.status_code == 200

    stored = client.get(f"{RUNS_PATH}/run-alpha")

    assert stored.status_code == 200
    body = stored.json()
    assert body["request_id"] == "run-alpha"
    assert body["question"] == ANSWERABLE
    assert body["retriever"] == "fake"
    assert body["status"] == run.json()["status"]
    assert body["stop_reason"] in {
        "evidence_sufficient",
        "no_evidence",
        "insufficient_evidence",
        "budget_spent",
    }
    assert body["report"] == run.json()["report"]
    assert body["citations"] == run.json()["citations"]
    assert body["steps_used"] == run.json()["steps_used"]
    assert body["trace"] == run.json()["trace"]
    assert body["notes"]
    assert body["trace"][-1]["event"] == "stop"


def test_the_trace_download_is_the_stored_run_not_a_second_performance(
    client: TestClient,
) -> None:
    run = client.post(
        RESEARCH_PATH,
        json={"question": OFF_CORPUS, "max_steps": 3},
        headers={REQUEST_ID_HEADER: "run-refused"},
    )
    assert run.status_code == 200
    assert run.json()["status"] == "refused"

    downloaded = client.get(f"{RUNS_PATH}/run-refused/trace.json")

    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/json")
    assert (
        downloaded.headers["content-disposition"]
        == 'attachment; filename="trace-run-refused.json"'
    )
    assert downloaded.json() == run.json()["trace"]


def test_an_unknown_id_is_a_typed_404(client: TestClient) -> None:
    response = client.get(f"{RUNS_PATH}/never-stored")

    assert response.status_code == 404
    assert response.json()["error_type"] == "not_found"
    assert "this process" in response.json()["error"]


def test_the_store_evicts_the_oldest_run_when_full() -> None:
    store = RunStore(capacity=2)
    first = RunArtifact.from_state(
        build_state(question="one?"), request_id="r1", retriever="fake"
    )
    second = RunArtifact.from_state(
        build_state(question="two?"), request_id="r2", retriever="fake"
    )
    third = RunArtifact.from_state(
        build_state(question="three?"), request_id="r3", retriever="fake"
    )

    store.put(first)
    store.put(second)
    store.put(third)

    assert len(store) == 2
    assert store.get("r1") is None
    assert store.get("r2") is not None
    assert store.get("r3") is not None
    assert store.ids() == ("r2", "r3")


def test_re_storing_an_id_replaces_it_and_marks_it_newest() -> None:
    store = RunStore(capacity=2)
    store.put(RunArtifact.from_state(build_state(), request_id="a", retriever="fake"))
    store.put(RunArtifact.from_state(build_state(), request_id="b", retriever="fake"))
    replacement = RunArtifact.from_state(
        build_state(question="replaced?"), request_id="a", retriever="fake"
    )

    store.put(replacement)

    assert store.ids() == ("b", "a")
    assert store.get("a") is not None
    assert store.get("a").question == "replaced?"


def test_capacity_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        RunStore(capacity=0)


def test_an_unfinished_run_cannot_be_stored() -> None:
    from agentic_rag.agent.state import ResearchState

    with pytest.raises(ValueError, match="terminal"):
        RunArtifact.from_state(
            ResearchState(question="still going"),
            request_id="x",
            retriever="fake",
        )


def test_the_service_puts_every_finished_run_into_its_store() -> None:
    service = ResearchService(retriever_factory=RecordingFactory())
    response = service.run(
        ResearchRequest(question=ANSWERABLE, max_steps=4),
        request_id="stored-by-service",
    )

    artifact = service.runs.get("stored-by-service")
    assert artifact is not None
    assert artifact.request_id == response.request_id
    assert artifact.report == response.report
    assert artifact.steps_used == response.steps_used


def test_default_capacity_is_small_enough_to_fit_in_process_memory() -> None:
    assert 1 <= DEFAULT_RUN_CAPACITY <= 64


def test_run_routes_are_in_the_openapi_document() -> None:
    with TestClient(create_app()) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert "/v1/runs/{run_id}" in paths
    assert "/v1/runs/{run_id}/trace.json" in paths
    assert "get" in paths["/v1/runs/{run_id}"]
    assert "get" in paths["/v1/runs/{run_id}/trace.json"]


def test_a_stub_runner_still_leaves_a_fetchable_artifact() -> None:
    state = build_state(steps=2)
    service = ResearchService(
        runner=StubRunner(state=state),
        retriever_factory=RecordingFactory(),
    )

    with TestClient(create_app(service)) as client:
        run = client.post(
            RESEARCH_PATH,
            json={"question": ANSWERABLE, "max_steps": 4},
            headers={REQUEST_ID_HEADER: "stubbed"},
        )
        stored = client.get(f"{RUNS_PATH}/stubbed")

    assert run.status_code == 200
    assert stored.status_code == 200
    assert stored.json()["trace"] == [event.model_dump(mode="json") for event in state.trace]
