"""``POST /v1/research`` over the test client: the contract, and every way it fails.

Nothing here opens a socket. The application is built around a service whose retriever
factory always yields the in-process fixture, or around a stub runner when the case
needs an outcome the free path cannot produce on demand. A ``PRODUCTION_RAG_URL`` left
set in a shell cannot change what any of these assert.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentic_rag.agent.state import ResearchState, ResearchStatus
from agentic_rag.api.errors import ErrorType
from agentic_rag.api.request_id import REQUEST_ID_HEADER
from agentic_rag.api.schemas import (
    MAX_MAX_STEPS,
    MAX_QUESTION_CHARS,
    MAX_TOP_K,
    RetrieverChoice,
)
from agentic_rag.api.service import ResearchService
from agentic_rag.main import create_app
from agentic_rag.tools.base import ToolError
from agentic_rag.tools.retrieve import DEFAULT_TOP_K, PRODUCTION_RAG_URL_ENV, RetrieveTool

from .conftest import ANSWERABLE, OFF_CORPUS, RecordingFactory, StubRunner, build_state

RESEARCH = "/v1/research"
THIN = "How does chunking work?"
UNREACHABLE_URL = "http://127.0.0.1:9"

RESPONSE_FIELDS = {"status", "report", "citations", "steps_used", "trace", "request_id"}
ERROR_FIELDS = {"error", "error_type", "request_id"}


@pytest.fixture
def client(offline_service: ResearchService) -> Iterator[TestClient]:
    """The real loop behind the route, pinned to the in-process backend."""
    with TestClient(create_app(offline_service)) as running:
        yield running


def client_over(service: ResearchService, *, raise_server_exceptions: bool = True) -> TestClient:
    """Return a client for an application built around ``service``."""
    return TestClient(create_app(service), raise_server_exceptions=raise_server_exceptions)


def ask(client: TestClient, **payload: Any) -> Any:
    """POST a research request and return the response."""
    return client.post(RESEARCH, json=payload)


# --- the answer, the refusal, and the budget ---------------------------------------


def test_a_grounded_answer_is_a_200_with_exactly_the_contract_fields(client: TestClient) -> None:
    response = ask(client, question=ANSWERABLE)
    body = response.json()

    assert response.status_code == 200
    assert set(body) == RESPONSE_FIELDS
    assert body["status"] == "done"
    assert body["steps_used"] >= 1
    assert body["citations"]
    assert body["trace"][-1]["event"] == "stop"


def test_every_marker_in_the_report_resolves_to_a_citation(client: TestClient) -> None:
    body = ask(client, question=ANSWERABLE).json()

    for citation in body["citations"]:
        assert f"[{citation['marker']}]" in body["report"]
        assert citation["chunk_id"]
        assert citation["source_path"]


def test_a_refusal_is_a_200_and_says_so_in_the_status(client: TestClient) -> None:
    body = ask(client, question=OFF_CORPUS, max_steps=3).json()

    assert body["status"] == "refused"
    assert body["citations"] == []
    assert "Refused" in body["report"]
    assert body["trace"][-1]["payload"]["reason"] == "no_evidence"


def test_an_exhausted_budget_is_a_200_that_reports_what_it_grounded(client: TestClient) -> None:
    body = ask(client, question=THIN, max_steps=1, top_k=1).json()

    assert body["status"] == "budget_exhausted"
    assert body["steps_used"] == 1
    assert "Status: partial." in body["report"]
    assert body["citations"]


def test_the_defaults_are_applied_when_only_a_question_is_sent() -> None:
    runner = StubRunner()
    with client_over(ResearchService(runner=runner, retriever_factory=RecordingFactory())) as c:
        ask(c, question=ANSWERABLE)

    assert runner.calls[0].top_k == DEFAULT_TOP_K


@pytest.mark.parametrize("status", [s for s in ResearchStatus if s is not ResearchStatus.RUNNING])
def test_every_terminal_status_serialises_through_the_route(status: ResearchStatus) -> None:
    runner = StubRunner(state=build_state(status=status))
    with client_over(ResearchService(runner=runner, retriever_factory=RecordingFactory())) as c:
        response = ask(c, question=ANSWERABLE)

    assert response.status_code == 200
    assert response.json()["status"] == status.value


# --- boundaries and rejected requests ----------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_steps", MAX_MAX_STEPS), ("top_k", MAX_TOP_K), ("max_steps", 1), ("top_k", 1)],
)
def test_the_boundaries_are_accepted(client: TestClient, field: str, value: int) -> None:
    assert ask(client, question=ANSWERABLE, **{field: value}).status_code == 200


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_steps", MAX_MAX_STEPS + 1),
        ("max_steps", 0),
        ("top_k", MAX_TOP_K + 1),
        ("top_k", 0),
    ],
)
def test_one_past_a_boundary_is_rejected(client: TestClient, field: str, value: int) -> None:
    response = ask(client, question=ANSWERABLE, **{field: value})

    assert response.status_code == 422
    assert response.json()["error_type"] == ErrorType.VALIDATION_ERROR.value
    assert field in response.json()["error"]


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_question_is_rejected(client: TestClient, blank: str) -> None:
    assert ask(client, question=blank).status_code == 422


def test_an_oversized_question_is_rejected(client: TestClient) -> None:
    assert ask(client, question="q" * (MAX_QUESTION_CHARS + 1)).status_code == 422


def test_a_missing_question_is_rejected(client: TestClient) -> None:
    response = ask(client, max_steps=2)

    assert response.status_code == 422
    assert "question" in response.json()["error"]


def test_an_unknown_field_is_rejected_and_named(client: TestClient) -> None:
    response = ask(client, question=ANSWERABLE, max_step=2)

    assert response.status_code == 422
    assert "max_step" in response.json()["error"]


def test_an_unknown_retriever_is_rejected(client: TestClient) -> None:
    response = ask(client, question=ANSWERABLE, retriever="openai")

    assert response.status_code == 422
    assert "retriever" in response.json()["error"]


def test_a_rejection_does_not_echo_the_rejected_value(client: TestClient) -> None:
    secret = "sk-not-a-real-key-0123456789-abcdefgh"
    response = ask(client, question=secret, max_steps=99)

    assert response.status_code == 422
    assert secret not in response.text


def test_a_malformed_body_is_a_typed_rejection(client: TestClient) -> None:
    response = client.post(
        RESEARCH, content=b"{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert set(response.json()) == ERROR_FIELDS


# --- configuration and backend failures --------------------------------------------


def test_choosing_http_without_configuration_is_capability_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PRODUCTION_RAG_URL_ENV, raising=False)

    with client_over(ResearchService()) as c:
        response = ask(c, question=ANSWERABLE, retriever=RetrieverChoice.HTTP.value)

    assert response.status_code == 503
    assert response.json()["error_type"] == ErrorType.CAPABILITY_MISSING.value
    assert PRODUCTION_RAG_URL_ENV in response.json()["error"]


def test_capability_missing_is_not_a_silent_fake_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PRODUCTION_RAG_URL_ENV, raising=False)

    with client_over(ResearchService()) as c:
        body = ask(c, question=ANSWERABLE, retriever=RetrieverChoice.HTTP.value).json()

    assert set(body) == ERROR_FIELDS
    assert "report" not in body
    assert "fake" not in body["error"].lower().replace("free retriever", "")


def test_a_backend_failure_is_503_without_the_backend_message() -> None:
    leaked = f"{UNREACHABLE_URL}/v1/query did not answer: [Errno 111] Connection refused"
    service = ResearchService(
        runner=StubRunner(error=ToolError(leaked)),
        retriever_factory=RecordingFactory(),
    )

    with client_over(service) as c:
        response = ask(c, question=ANSWERABLE)

    assert response.status_code == 503
    assert response.json()["error_type"] == ErrorType.BACKEND_UNAVAILABLE.value
    assert UNREACHABLE_URL not in response.text
    assert "Errno" not in response.text


def test_a_programming_defect_is_500_and_never_a_backend_failure() -> None:
    service = ResearchService(
        runner=StubRunner(error=ZeroDivisionError("division by zero in this service")),
        retriever_factory=RecordingFactory(),
    )

    with client_over(service, raise_server_exceptions=False) as c:
        response = ask(c, question=ANSWERABLE)

    body = response.json()
    assert response.status_code == 500
    assert body["error_type"] == ErrorType.INTERNAL_ERROR.value
    assert body["error_type"] != ErrorType.BACKEND_UNAVAILABLE.value
    assert set(body) == ERROR_FIELDS


def test_a_defect_leaks_neither_traceback_nor_message() -> None:
    service = ResearchService(
        runner=StubRunner(error=ZeroDivisionError("division by zero in this service")),
        retriever_factory=RecordingFactory(),
    )

    with client_over(service, raise_server_exceptions=False) as c:
        response = ask(c, question=ANSWERABLE)

    assert "Traceback" not in response.text
    assert "ZeroDivisionError" not in response.text
    assert "division by zero" not in response.text
    assert ".py" not in response.text


def test_a_run_that_never_finished_is_an_internal_error_not_a_backend_failure() -> None:
    unfinished = ResearchState(question=ANSWERABLE)
    service = ResearchService(
        runner=StubRunner(state=unfinished),
        retriever_factory=RecordingFactory(),
    )

    with client_over(service, raise_server_exceptions=False) as c:
        response = ask(c, question=ANSWERABLE)

    assert response.status_code == 500
    assert response.json()["error_type"] == ErrorType.INTERNAL_ERROR.value


# --- correlation ---------------------------------------------------------------------


def test_a_minted_id_is_echoed_in_the_header_and_the_body(client: TestClient) -> None:
    response = ask(client, question=ANSWERABLE)

    assert response.headers[REQUEST_ID_HEADER] == response.json()["request_id"]


def test_a_caller_id_is_kept(client: TestClient) -> None:
    response = client.post(
        RESEARCH,
        json={"question": ANSWERABLE},
        headers={REQUEST_ID_HEADER: "caller-run-42"},
    )

    assert response.headers[REQUEST_ID_HEADER] == "caller-run-42"
    assert response.json()["request_id"] == "caller-run-42"


@pytest.mark.parametrize(
    "unsafe",
    ["run 42", "run\ninjected", "<script>", "z" * 500, "", "%0d%0aSet-Cookie:+x=1"],
)
def test_an_unsafe_caller_id_is_replaced_and_never_echoed(
    client: TestClient, unsafe: str
) -> None:
    response = client.post(
        RESEARCH, json={"question": ANSWERABLE}, headers={REQUEST_ID_HEADER: unsafe}
    )

    echoed = response.headers[REQUEST_ID_HEADER]
    assert echoed != unsafe
    assert echoed == response.json()["request_id"]
    assert unsafe.strip() not in response.text or not unsafe.strip()


def test_a_rejected_request_still_carries_a_correlation_id(client: TestClient) -> None:
    response = ask(client, question="")

    assert response.json()["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_an_unknown_path_answers_in_the_same_envelope(client: TestClient) -> None:
    response = client.get("/v1/nope")

    assert response.status_code == 404
    assert set(response.json()) == ERROR_FIELDS
    assert response.json()["error_type"] == ErrorType.NOT_FOUND.value
    assert response.headers[REQUEST_ID_HEADER]


def test_a_wrong_method_answers_in_the_same_envelope(client: TestClient) -> None:
    response = client.get(RESEARCH)

    assert response.status_code == 405
    assert response.json()["error_type"] == ErrorType.METHOD_NOT_ALLOWED.value


# --- determinism and isolation --------------------------------------------------------


def test_two_identical_requests_differ_only_in_their_correlation_id(client: TestClient) -> None:
    first = ask(client, question=ANSWERABLE).json()
    second = ask(client, question=ANSWERABLE).json()

    assert first.pop("request_id") != second.pop("request_id")
    assert first == second


def test_concurrent_requests_do_not_leak_ids_or_state() -> None:
    """Every request is forced to overlap every other, then checked for cross-talk.

    The barrier is what makes this a concurrency test rather than a loop: no request may
    return until all of them are inside the runner, so any shared mutable state would
    have to be shared *at the same moment*.
    """
    concurrency = 8
    barrier = Barrier(concurrency, timeout=10)

    def runner(question: str, **_: Any) -> ResearchState:
        barrier.wait()
        return build_state(question=question)

    service = ResearchService(runner=runner, retriever_factory=RecordingFactory())

    with client_over(service) as c:

        def call(index: int) -> tuple[str, str]:
            response = c.post(
                RESEARCH,
                json={"question": f"question number {index}"},
                headers={REQUEST_ID_HEADER: f"caller-{index}"},
            )
            body = response.json()
            return body["request_id"], body["report"]

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(call, range(concurrency)))

    for index, (request_id, report) in enumerate(results):
        assert request_id == f"caller-{index}"
        assert f"question number {index}" in report
    assert len({request_id for request_id, _ in results}) == concurrency


def test_two_applications_do_not_share_a_service() -> None:
    first = ResearchService(runner=StubRunner(), retriever_factory=RecordingFactory())
    second_factory = RecordingFactory()
    second = ResearchService(runner=StubRunner(), retriever_factory=second_factory)

    with client_over(first) as a, client_over(second) as b:
        ask(a, question=ANSWERABLE)
        ask(b, question=ANSWERABLE, retriever=RetrieverChoice.HTTP.value)

    assert second_factory.choices == [RetrieverChoice.HTTP]


def test_the_route_never_builds_its_own_retriever(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PRODUCTION_RAG_URL_ENV, UNREACHABLE_URL)
    factory = RecordingFactory()
    runner = StubRunner()

    with client_over(ResearchService(runner=runner, retriever_factory=factory)) as c:
        ask(c, question=ANSWERABLE)

    tool = runner.calls[0].tool
    assert isinstance(tool, RetrieveTool)
    assert tool.backend_name == "fake"
