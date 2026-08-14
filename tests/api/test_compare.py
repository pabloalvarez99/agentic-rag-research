"""Compare is payload-in, typed-diff-out, and never resolves a server id."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from agentic_rag.api.compare import COMPARE_PATH, CompareResponse, compare_runs
from agentic_rag.api.request_id import REQUEST_ID_HEADER
from agentic_rag.api.routes import RESEARCH_PATH, RUNS_PATH
from agentic_rag.api.runs import RunArtifact
from agentic_rag.api.service import ResearchService
from agentic_rag.main import create_app

from .conftest import ANSWERABLE, OFF_CORPUS, build_state


@pytest.fixture
def client(offline_service: ResearchService) -> Iterator[TestClient]:
    """Serve compare over a service that cannot reach a network."""
    with TestClient(create_app(offline_service)) as running:
        yield running


def _artifact(client: TestClient, *, question: str, request_id: str) -> dict:
    run = client.post(
        RESEARCH_PATH,
        json={"question": question, "max_steps": 4},
        headers={REQUEST_ID_HEADER: request_id},
    )
    assert run.status_code == 200
    stored = client.get(f"{RUNS_PATH}/{request_id}")
    assert stored.status_code == 200
    return stored.json()


def test_identical_fixtures_yield_an_empty_byte_stable_diff() -> None:
    left = RunArtifact.from_state(build_state(), request_id="same", retriever="fake")
    right = RunArtifact.from_state(build_state(), request_id="same", retriever="fake")

    first = compare_runs(left, right)
    second = compare_runs(left, right)

    assert first.identical is True
    assert first.diffs == ()
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert json.dumps(first.model_dump(mode="json"), sort_keys=True) == json.dumps(
        second.model_dump(mode="json"), sort_keys=True
    )


def test_refused_vs_done_yields_typed_field_diffs(client: TestClient) -> None:
    done = _artifact(client, question=ANSWERABLE, request_id="cmp-done")
    refused = _artifact(client, question=OFF_CORPUS, request_id="cmp-refused")

    response = client.post(COMPARE_PATH, json={"left": done, "right": refused})

    assert response.status_code == 200
    body = response.json()
    assert body["identical"] is False
    fields = [row["field"] for row in body["diffs"]]
    assert "status" in fields
    assert "stop_reason" in fields
    assert fields == sorted(fields, key=lambda name: fields.index(name))
    # Field order is product order, not alphabetical: status before stop_reason.
    assert fields.index("status") < fields.index("stop_reason")
    assert body["left_request_id"] == "cmp-done"
    assert body["right_request_id"] == "cmp-refused"
    # Diffs are byte-stable for the same payloads.
    again = client.post(COMPARE_PATH, json={"left": done, "right": refused})
    assert again.json() == body


def test_compare_does_not_require_ids_to_still_exist_in_the_store(client: TestClient) -> None:
    done = _artifact(client, question=ANSWERABLE, request_id="will-evict")
    # Evict by filling the store if needed is unnecessary: compare never looks up.
    # Delete-equivalent: a payload with an id the store never held.
    orphan = dict(done)
    orphan["request_id"] = "never-stored-anywhere"

    response = client.post(COMPARE_PATH, json={"left": done, "right": orphan})

    assert response.status_code == 200
    assert response.json()["identical"] is True
    assert client.get(f"{RUNS_PATH}/never-stored-anywhere").status_code == 404


def test_full_run_download_is_an_attachment(client: TestClient) -> None:
    _artifact(client, question=ANSWERABLE, request_id="dl-run")

    downloaded = client.get(f"{RUNS_PATH}/dl-run/run.json")

    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/json")
    assert (
        downloaded.headers["content-disposition"]
        == 'attachment; filename="run-dl-run.json"'
    )
    body = downloaded.json()
    assert body["request_id"] == "dl-run"
    assert "stop_reason" in body
    assert "notes" in body
    assert "citations" in body


def test_compare_route_is_in_the_openapi_document() -> None:
    with TestClient(create_app()) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert COMPARE_PATH in paths
    assert "post" in paths[COMPARE_PATH]
    assert "/v1/runs/{run_id}/run.json" in paths


def test_compare_response_schema_is_typed() -> None:
    left = RunArtifact.from_state(build_state(), request_id="a", retriever="fake")
    right = RunArtifact.from_state(
        build_state(question="other?"), request_id="b", retriever="fake"
    )

    result = compare_runs(left, right)

    assert isinstance(result, CompareResponse)
    assert result.identical is False
    assert any(diff.field == "question" for diff in result.diffs)


def test_unknown_fields_on_compare_request_are_rejected(client: TestClient) -> None:
    artifact = _artifact(client, question=ANSWERABLE, request_id="strict")

    response = client.post(
        COMPARE_PATH,
        json={"left": artifact, "right": artifact, "extra": True},
    )

    assert response.status_code == 422
