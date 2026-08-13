"""What the loop does when a tool cannot produce a result.

`ToolError` is the failure a tool is documented to raise, and the one a run
against a real retrieval service will eventually meet. Every test here asserts
the same three things in a different shape: the run ends instead of unwinding,
it says `degraded` and means it, and it pays for the attempt.
"""

from __future__ import annotations

import json
import re

import pytest

from agentic_rag.agent import (
    ResearchState,
    ResearchStatus,
    run_research,
)
from agentic_rag.tools import (
    FakeRetrievalBackend,
    RetrieveRequest,
    RetrieveTool,
    ToolError,
)
from reliability.backends import SECRET_SHAPED, ExplodingBackend, FailingBackend, corpus

TWO_STEP_QUESTION = (
    "Explain chunking in detail for the record and explain refusal policy in detail as well"
)
"""Long enough to plan two sub-questions, and answered thinly enough to need both."""

SMALL_CORPUS = corpus("Chunking splits a document.", "Refusal names the gap.")

MARKER = re.compile(r"\[(\d+)\]")


def two_step_tool(*, fail_from: int) -> RetrieveTool:
    return RetrieveTool(
        FailingBackend(fail_from=fail_from, delegate=FakeRetrievalBackend(SMALL_CORPUS))
    )


def test_a_tool_failure_ends_the_run_instead_of_unwinding_it() -> None:
    state = run_research(TWO_STEP_QUESTION, tool=two_step_tool(fail_from=1), max_steps=4)

    assert state.status is ResearchStatus.DEGRADED
    assert state.stop_reason == "tool_failed"
    assert state.is_finished
    assert state.trace[-1].event == "stop"


def test_a_failed_call_spends_a_step() -> None:
    state = run_research(TWO_STEP_QUESTION, tool=two_step_tool(fail_from=1), max_steps=4)

    assert state.steps_taken == 1
    assert state.budget_remaining == 3
    assert state.steps[-1].failed
    assert not state.steps[-1].found_evidence
    assert state.trace[-1].payload["steps_used"] == 1


def test_a_failure_on_the_only_affordable_step_is_degraded_not_budget_exhausted() -> None:
    state = run_research(TWO_STEP_QUESTION, tool=two_step_tool(fail_from=1), max_steps=1)

    assert state.budget_spent
    assert state.status is ResearchStatus.DEGRADED
    assert state.stop_reason == "tool_failed"


def test_a_failure_after_evidence_reports_what_the_run_grounded() -> None:
    state = run_research(TWO_STEP_QUESTION, tool=two_step_tool(fail_from=2), max_steps=4)
    assert state.report is not None

    assert state.status is ResearchStatus.DEGRADED
    assert state.steps_taken == 2
    assert state.evidence_ids == ("doc-1",)
    assert [citation.chunk_id for citation in state.citations] == ["doc-1"]
    assert [int(marker) for marker in MARKER.findall(state.report)] == [1]
    assert "Status: degraded." in state.report


def test_a_failure_before_any_evidence_reports_that_no_answer_is_available() -> None:
    state = run_research(TWO_STEP_QUESTION, tool=two_step_tool(fail_from=1), max_steps=4)
    assert state.report is not None

    assert not state.has_evidence
    assert state.citations == []
    assert MARKER.findall(state.report) == []
    assert "Unavailable:" in state.report


def test_the_report_names_the_failure_in_the_words_the_trace_recorded() -> None:
    state = run_research(TWO_STEP_QUESTION, tool=two_step_tool(fail_from=2), max_steps=4)
    assert state.report is not None
    failure = state.last_tool_failure
    assert failure is not None

    assert failure.detail in state.report
    assert state.trace[-3].payload["detail"] == failure.detail


def test_a_tool_failure_is_traced_between_its_call_and_the_synthesis() -> None:
    state = run_research(TWO_STEP_QUESTION, tool=two_step_tool(fail_from=1), max_steps=4)

    assert [event.event for event in state.trace] == [
        "plan_created",
        "tool_call",
        "tool_error",
        "synthesize",
        "stop",
    ]
    call, error = state.trace[1], state.trace[2]
    assert error.payload["tool"] == call.payload["tool"] == "retrieve"
    assert error.payload["question"] == call.payload["question"]
    assert error.payload["error_type"] == "tool_error"


def test_the_run_stops_at_the_first_failure_and_never_calls_the_tool_again() -> None:
    backend = FailingBackend(fail_from=1, delegate=FakeRetrievalBackend(SMALL_CORPUS))

    state = run_research(TWO_STEP_QUESTION, tool=RetrieveTool(backend), max_steps=20)

    assert backend.calls == 1, "a failed call is not retried, with any budget"
    assert [event.event for event in state.trace].count("tool_error") == 1
    assert state.steps_taken == 1


def test_no_word_of_the_tool_s_error_reaches_the_run() -> None:
    message = f"https://user:{SECRET_SHAPED}@retrieval.invalid/v1/query refused the connection"
    backend = FailingBackend(fail_from=1, message=message)

    state = run_research(TWO_STEP_QUESTION, tool=RetrieveTool(backend), max_steps=4)

    serialised = json.dumps(state.model_dump(mode="json"), ensure_ascii=False)
    assert SECRET_SHAPED not in serialised
    assert "retrieval.invalid" not in serialised
    assert "refused the connection" not in serialised


def test_an_unexpected_exception_is_not_dressed_up_as_a_degraded_run() -> None:
    backend = ExplodingBackend()

    with pytest.raises(RuntimeError, match="backend bug"):
        run_research(TWO_STEP_QUESTION, tool=RetrieveTool(backend), max_steps=4)


def test_a_tool_error_raised_by_the_tool_itself_is_handled_the_same_way() -> None:
    class BrokenTool:
        name = "retrieve"
        description = "raises before it reaches a backend"

        def run(self, request: RetrieveRequest) -> object:
            raise ToolError("the tool could not build a request")

    state = run_research(TWO_STEP_QUESTION, tool=BrokenTool(), max_steps=4)  # type: ignore[arg-type]

    assert state.status is ResearchStatus.DEGRADED
    assert state.steps_taken == 1


def test_a_failed_step_is_reported_as_failed_and_not_as_answered_by_nothing() -> None:
    state = ResearchState(question=TWO_STEP_QUESTION, max_steps=2)
    state.record_plan(["chunking"])
    state.record_tool_failure("retrieve", RetrieveRequest(question="chunking"))

    assert state.failed_sub_questions == ("chunking",)
    assert state.unanswered_sub_questions == (), (
        "a sub-question whose tool failed was never asked of the corpus"
    )
    assert state.has_tool_failure


def test_a_step_that_found_nothing_is_still_not_a_failure() -> None:
    state = run_research(
        "What were the quarterly revenues in Patagonia?",
        tool=RetrieveTool(FakeRetrievalBackend()),
        max_steps=2,
    )

    assert state.status is ResearchStatus.REFUSED
    assert not state.has_tool_failure
    assert state.failed_sub_questions == ()
    assert state.unanswered_sub_questions
