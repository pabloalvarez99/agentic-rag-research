"""The application service: one path from a request to a run, and what it refuses to do.

The backend-selection tests are the load-bearing ones. Two silent substitutions would be
serious, and in opposite directions: a run that was asked for the fixture but reached the
network, and a run that was asked for a real retrieval service and quietly received
deterministic canned passages. The second is worse — a caller would read them as
evidence — and it is the one a convenience fallback introduces.
"""

from __future__ import annotations

import pytest

from agentic_rag.agent.state import ResearchState, ResearchStatus
from agentic_rag.api.errors import BackendUnavailable, CapabilityMissing, RunNotReportable
from agentic_rag.api.schemas import ResearchRequest, ResearchResponse, RetrieverChoice
from agentic_rag.api.service import ResearchService, build_retriever, render_response
from agentic_rag.tools.base import ToolError
from agentic_rag.tools.retrieve import PRODUCTION_RAG_URL_ENV

from .conftest import ANSWERABLE, OFF_CORPUS, RecordingFactory, StubRunner, build_state

UNREACHABLE_URL = "http://127.0.0.1:9"


def test_the_fake_backend_never_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PRODUCTION_RAG_URL_ENV, UNREACHABLE_URL)

    assert build_retriever(RetrieverChoice.FAKE).backend_name == "fake"


def test_choosing_http_without_configuration_is_a_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PRODUCTION_RAG_URL_ENV, raising=False)

    with pytest.raises(CapabilityMissing) as refused:
        build_retriever(RetrieverChoice.HTTP)

    assert PRODUCTION_RAG_URL_ENV in str(refused.value)


def test_choosing_http_without_configuration_does_not_fall_back_to_the_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PRODUCTION_RAG_URL_ENV, "   ")

    with pytest.raises(CapabilityMissing):
        build_retriever(RetrieverChoice.HTTP)


def test_the_configuration_error_names_the_variable_and_not_its_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PRODUCTION_RAG_URL_ENV, raising=False)

    with pytest.raises(CapabilityMissing) as refused:
        build_retriever(RetrieverChoice.HTTP)

    assert "http://" not in str(refused.value)


def test_a_configured_http_backend_is_selected_without_calling_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PRODUCTION_RAG_URL_ENV, UNREACHABLE_URL)

    assert build_retriever(RetrieverChoice.HTTP).backend_name == "production-rag"


def test_the_request_bounds_reach_the_runner_unchanged() -> None:
    runner = StubRunner()
    service = ResearchService(runner=runner, retriever_factory=RecordingFactory())

    service.run(ResearchRequest(question=ANSWERABLE, max_steps=7, top_k=2))

    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert (call.question, call.max_steps, call.top_k) == (ANSWERABLE, 7, 2)
    assert call.tool is not None


def test_the_chosen_backend_is_the_one_the_factory_is_asked_for() -> None:
    factory = RecordingFactory()
    service = ResearchService(runner=StubRunner(), retriever_factory=factory)

    service.run(ResearchRequest(question=ANSWERABLE, retriever=RetrieverChoice.HTTP))

    assert factory.choices == [RetrieverChoice.HTTP]


def test_a_run_without_a_caller_id_still_carries_one() -> None:
    service = ResearchService(runner=StubRunner(), retriever_factory=RecordingFactory())

    assert service.run(ResearchRequest(question=ANSWERABLE)).request_id


def test_a_caller_id_is_carried_into_the_response() -> None:
    service = ResearchService(runner=StubRunner(), retriever_factory=RecordingFactory())

    response = service.run(ResearchRequest(question=ANSWERABLE), request_id="run-42")

    assert response.request_id == "run-42"


def test_a_backend_failure_becomes_a_typed_error_without_the_backend_message() -> None:
    leaked = f"{UNREACHABLE_URL}/v1/query did not answer: connection refused"
    service = ResearchService(
        runner=StubRunner(error=ToolError(leaked)),
        retriever_factory=RecordingFactory(),
    )

    with pytest.raises(BackendUnavailable) as failure:
        service.run(ResearchRequest(question=ANSWERABLE))

    assert leaked not in str(failure.value)
    assert "http://" not in str(failure.value)


def test_an_unexpected_error_is_not_dressed_up_as_a_backend_failure() -> None:
    service = ResearchService(
        runner=StubRunner(error=ZeroDivisionError("a defect in this service")),
        retriever_factory=RecordingFactory(),
    )

    with pytest.raises(ZeroDivisionError):
        service.run(ResearchRequest(question=ANSWERABLE))


def test_an_unfinished_run_cannot_be_reported() -> None:
    with pytest.raises(RunNotReportable):
        render_response(ResearchState(question=ANSWERABLE), request_id="run-42")


def test_a_terminal_run_without_a_report_cannot_be_reported() -> None:
    state = ResearchState(question=ANSWERABLE)
    state.record_plan([ANSWERABLE])
    state.finish(ResearchStatus.REFUSED, "no_evidence")

    with pytest.raises(RunNotReportable):
        render_response(state, request_id="run-42")


@pytest.mark.parametrize("status", [s for s in ResearchStatus if s is not ResearchStatus.RUNNING])
def test_every_status_the_loop_can_end_in_is_reportable(status: ResearchStatus) -> None:
    response = render_response(build_state(status=status), request_id="run-42")

    assert response.status is status
    assert response.model_dump_json()


def test_the_real_loop_answers_from_the_committed_corpus(offline_service: ResearchService) -> None:
    response = offline_service.run(ResearchRequest(question=ANSWERABLE))

    assert response.status is ResearchStatus.DONE
    assert response.citations
    assert response.steps_used >= 1
    assert response.trace[-1].event == "stop"
    assert all(f"[{citation.marker}]" in response.report for citation in response.citations)


def test_the_real_loop_refuses_what_the_corpus_cannot_support(
    offline_service: ResearchService,
) -> None:
    response = offline_service.run(ResearchRequest(question=OFF_CORPUS))

    assert response.status is ResearchStatus.REFUSED
    assert response.citations == []
    assert "Refused" in response.report


def test_a_repeated_request_differs_only_in_its_correlation_id(
    offline_service: ResearchService,
) -> None:
    request = ResearchRequest(question=ANSWERABLE)

    first = offline_service.run(request, request_id="first")
    second = offline_service.run(request, request_id="second")

    assert body(first) == body(second)


def test_one_service_answers_two_different_questions_independently(
    offline_service: ResearchService,
) -> None:
    answered = offline_service.run(ResearchRequest(question=ANSWERABLE))
    refused = offline_service.run(ResearchRequest(question=OFF_CORPUS))
    answered_again = offline_service.run(ResearchRequest(question=ANSWERABLE))

    assert refused.status is ResearchStatus.REFUSED
    assert body(answered) == body(answered_again)


def body(response: ResearchResponse) -> dict[str, object]:
    payload = response.model_dump()
    payload.pop("request_id")
    return payload
