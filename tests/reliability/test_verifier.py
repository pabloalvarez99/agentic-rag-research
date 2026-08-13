"""The verifier, checked the only way a verifier can be: by corrupting runs.

A checker that has never seen a broken run is a checker nobody knows the range
of. Each test here takes a real run, breaks exactly one thing about it, and
asserts the specific code comes back — and the last group asserts that reading a
run leaves it exactly as it was found.

Every corruption is built by editing a finished state, because that is the shape
the problem arrives in: a trace that was serialised, moved, stored and read back
by something that had every opportunity to reorder or rewrite it.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest

from agentic_rag.agent import (
    ResearchState,
    ResearchStatus,
    RunAlreadyFinished,
    StopReason,
    Synthesis,
    TraceEvent,
    critique,
    run_research,
    tool_failure,
)
from agentic_rag.tools import FakeRetrievalBackend, RetrieveRequest, RetrieveTool
from agentic_rag.verification import stop_reasons_for, verify_run
from reliability.backends import FailingBackend, corpus

ANSWERABLE = "What does hybrid retrieval buy over dense retrieval alone?"
OFF_CORPUS = "What were the quarterly revenues in Patagonia?"
TWO_STEP = "Explain chunking in detail for the record and explain refusal policy in detail as well"


def run(question: str = ANSWERABLE, **kwargs: Any) -> ResearchState:
    return run_research(question, tool=RetrieveTool(FakeRetrievalBackend()), **kwargs)


def repayload(event: TraceEvent, **changes: Any) -> TraceEvent:
    return event.model_copy(update={"payload": {**event.payload, **changes}})


def index_of(state: ResearchState, name: str) -> int:
    return next(index for index, event in enumerate(state.trace) if event.event == name)


# --- a run the loop produced holds everything --------------------------------


@pytest.mark.parametrize("question", [ANSWERABLE, OFF_CORPUS, TWO_STEP])
@pytest.mark.parametrize("max_steps", [1, 2, 4, 20])
def test_a_run_the_loop_produced_has_no_violations(question: str, max_steps: int) -> None:
    report = verify_run(run(question, max_steps=max_steps))

    assert report.ok, report.summary()


def test_a_degraded_run_has_no_violations() -> None:
    tool = RetrieveTool(
        FailingBackend(fail_from=2, delegate=FakeRetrievalBackend(corpus("Chunking splits.")))
    )

    report = verify_run(run_research(TWO_STEP, tool=tool, max_steps=4))

    assert report.ok, report.summary()


def test_a_run_still_in_progress_is_not_a_violation() -> None:
    state = ResearchState(question=ANSWERABLE)
    state.record_plan(["hybrid retrieval"])

    assert verify_run(state).ok


# --- event grammar and order --------------------------------------------------


def test_an_event_the_loop_cannot_record_is_named() -> None:
    state = run()
    state.trace.insert(1, TraceEvent.model_construct(event="exfiltrate", payload={}))

    report = verify_run(state)

    assert "unknown_event" in report.codes
    assert not report.ok


def test_a_critique_before_its_tool_result_breaks_the_grammar() -> None:
    state = run()
    result, critique = index_of(state, "tool_result"), index_of(state, "critique")
    state.trace[result], state.trace[critique] = state.trace[critique], state.trace[result]

    report = verify_run(state)

    assert "event_out_of_order" in report.codes
    violation = next(v for v in report.violations if v.code == "event_out_of_order")
    assert violation.event_index == result


def test_a_run_that_retried_after_a_failure_is_not_a_run_this_loop_produced() -> None:
    state = run()
    call = index_of(state, "tool_call")
    state.trace.insert(call + 1, TraceEvent(event="tool_error", payload={"tool": "retrieve"}))

    assert "event_out_of_order" in verify_run(state).codes


# --- call / outcome pairing ---------------------------------------------------


def test_a_tool_call_nothing_answered_is_named() -> None:
    state = run()
    del state.trace[index_of(state, "tool_result")]

    assert "tool_call_unresolved" in verify_run(state).codes


def test_a_second_result_for_one_call_is_named() -> None:
    state = run()
    result = index_of(state, "tool_result")
    state.trace.insert(result + 1, state.trace[result])

    assert "tool_outcome_unpaired" in verify_run(state).codes


# --- stopping -----------------------------------------------------------------


def test_a_finished_run_without_a_stop_event_is_named() -> None:
    state = run()
    del state.trace[-1]

    report = verify_run(state)

    assert "stop_missing" in report.codes
    assert "event_out_of_order" not in report.codes, "truncation is not an ordering problem"


def test_a_second_stop_is_named() -> None:
    state = run()
    state.trace.append(state.trace[-1])

    assert "stop_repeated" in verify_run(state).codes


def test_work_recorded_after_the_stop_is_named() -> None:
    state = run()
    state.trace.append(TraceEvent(event="critique", payload={"gaps": []}))

    report = verify_run(state)

    assert "stop_not_last" in report.codes
    assert "event_out_of_order" in report.codes


def test_a_stopped_trace_on_a_running_status_is_named() -> None:
    state = run()
    state.status = ResearchStatus.RUNNING
    state.stop_reason = None

    assert "status_not_terminal" in verify_run(state).codes


# --- status, reason and budget ------------------------------------------------


def test_a_status_that_cannot_carry_its_reason_is_named() -> None:
    state = run()
    state.stop_reason = "budget_spent"

    assert "status_reason_mismatch" in verify_run(state).codes


def test_a_running_run_that_already_has_a_reason_is_named() -> None:
    state = ResearchState(question=ANSWERABLE)
    state.record_plan(["hybrid retrieval"])
    state.stop_reason = "no_evidence"

    assert "status_reason_mismatch" in verify_run(state).codes


def test_more_steps_than_the_budget_allowed_is_named() -> None:
    state = run(TWO_STEP, max_steps=4)
    assert state.steps_taken >= 2
    state.max_steps = 1

    assert "budget_exceeded" in verify_run(state).codes


def test_every_terminal_status_has_at_least_one_reason_and_no_reason_has_two() -> None:
    terminal = [status for status in ResearchStatus if status.is_terminal]
    owners = {
        reason: [status for status in terminal if reason in stop_reasons_for(status)]
        for reason in get_args(StopReason)
    }

    assert all(stop_reasons_for(status) for status in terminal)
    assert all(len(statuses) == 1 for statuses in owners.values()), owners


# --- synthesis and report -----------------------------------------------------


def test_a_run_that_stopped_without_synthesising_is_named() -> None:
    state = run()
    del state.trace[index_of(state, "synthesize")]

    assert "synthesis_missing" in verify_run(state).codes


def test_a_finished_run_without_a_report_is_named() -> None:
    state = run()
    state.report = None

    assert "report_missing" in verify_run(state).codes


# --- citations ----------------------------------------------------------------


def test_a_marker_that_resolves_to_nothing_is_named() -> None:
    state = run()
    assert state.report is not None
    state.report = f"{state.report}\n- something nobody retrieved [99]"

    assert "citation_marker_unresolved" in verify_run(state).codes


def test_a_citation_the_report_never_prints_is_named() -> None:
    state = run()
    state.report = "Question: what does hybrid retrieval buy?"

    assert "citation_unprinted" in verify_run(state).codes


def test_citations_numbered_out_of_order_are_named() -> None:
    state = run()
    assert len(state.citations) >= 2
    state.citations = list(reversed(state.citations))

    assert "citation_out_of_order" in verify_run(state).codes


def test_a_citation_naming_a_chunk_the_run_never_retrieved_is_named() -> None:
    state = run()
    state.citations[0] = state.citations[0].model_copy(update={"chunk_id": "planted-1"})

    assert "citation_not_grounded" in verify_run(state).codes


def test_a_citation_pointing_at_another_document_is_named() -> None:
    state = run()
    state.citations[0] = state.citations[0].model_copy(
        update={"source_path": "docs/somewhere-else.md"}
    )

    assert "citation_not_grounded" in verify_run(state).codes


def test_a_snippet_edited_after_the_fact_is_named() -> None:
    state = run()
    state.citations[0] = state.citations[0].model_copy(
        update={"snippet": "Zebras outperform every retrieval strategy measured."}
    )

    assert "citation_not_grounded" in verify_run(state).codes


# --- evidence and plan --------------------------------------------------------


def test_the_same_chunk_held_twice_is_named() -> None:
    state = run()
    state.evidence.append(state.evidence[0])

    assert "evidence_duplicated" in verify_run(state).codes


def test_a_run_with_no_plan_event_is_named() -> None:
    state = run()
    del state.trace[index_of(state, "plan_created")]

    assert "plan_missing" in verify_run(state).codes


def test_a_run_that_kept_no_plan_is_named() -> None:
    state = run()
    state.plan = []

    report = verify_run(state)

    assert "plan_missing" in report.codes
    assert "trace_state_mismatch" in report.codes


# --- trace against state ------------------------------------------------------


def test_a_stop_event_that_undercounts_the_steps_is_named() -> None:
    state = run()
    state.trace[-1] = repayload(state.trace[-1], steps_used=0)

    assert "trace_state_mismatch" in verify_run(state).codes


def test_a_stop_event_renamed_to_another_outcome_is_named() -> None:
    state = run()
    state.trace[-1] = repayload(state.trace[-1], status="degraded", reason="tool_failed")

    assert "trace_state_mismatch" in verify_run(state).codes


def test_evidence_that_arrived_without_a_tool_result_is_named() -> None:
    state = run()
    planted = state.evidence[0].model_copy(update={"chunk_id": "planted-1"})
    state.evidence.append(planted)

    assert "trace_state_mismatch" in verify_run(state).codes


def test_a_tool_result_that_disowns_its_step_is_named() -> None:
    state = run()
    result = index_of(state, "tool_result")
    state.trace[result] = repayload(state.trace[result], evidence_ids=[])

    assert "trace_state_mismatch" in verify_run(state).codes


def test_a_failed_step_traced_as_a_completed_one_is_named() -> None:
    state = run()
    state.steps[0] = state.steps[0].model_copy(update={"failure": tool_failure("retrieve")})

    assert "trace_state_mismatch" in verify_run(state).codes


def test_a_plan_event_rewritten_after_the_run_is_named() -> None:
    state = run()
    plan = index_of(state, "plan_created")
    state.trace[plan] = repayload(state.trace[plan], sub_questions=["a different plan"])

    assert "trace_state_mismatch" in verify_run(state).codes


def test_gaps_that_no_critique_named_are_named() -> None:
    state = run(OFF_CORPUS, max_steps=2)
    assert state.gaps
    state.gaps = state.gaps[:1]

    assert "trace_state_mismatch" in verify_run(state).codes


def test_a_synthesis_event_that_counts_evidence_the_run_lacks_is_named() -> None:
    state = run()
    synthesis = index_of(state, "synthesize")
    state.trace[synthesis] = repayload(state.trace[synthesis], evidence_available=99)

    assert "trace_state_mismatch" in verify_run(state).codes


# --- the verifier writes nothing ----------------------------------------------


@pytest.mark.parametrize("question", [ANSWERABLE, OFF_CORPUS, TWO_STEP])
def test_verifying_a_run_leaves_it_exactly_as_it_was(question: str) -> None:
    state = run(question, max_steps=3)
    before = state.model_dump(mode="json")

    verify_run(state)

    assert state.model_dump(mode="json") == before


def test_verifying_a_corrupted_run_does_not_repair_it() -> None:
    state = run()
    state.trace.append(state.trace[-1])
    before = state.model_dump(mode="json")

    first = verify_run(state)
    second = verify_run(state)

    assert state.model_dump(mode="json") == before
    assert first == second, "verification is a function of the run, not of when it ran"


# --- the state refuses the corruptions it can refuse --------------------------


def test_a_finished_run_refuses_a_second_stop() -> None:
    state = run()

    with pytest.raises(RunAlreadyFinished):
        state.finish(ResearchStatus.DEGRADED, "tool_failed")


def test_a_finished_run_refuses_a_failed_step() -> None:
    state = run()

    with pytest.raises(RunAlreadyFinished):
        state.record_tool_failure("retrieve", RetrieveRequest(question="anything"))


def test_a_finished_run_refuses_every_kind_of_record() -> None:
    state = run()

    with pytest.raises(RunAlreadyFinished):
        state.record_plan(["another"])
    with pytest.raises(RunAlreadyFinished):
        state.record_tool_call("retrieve", RetrieveRequest(question="anything"))
    with pytest.raises(RunAlreadyFinished):
        state.record_synthesis(Synthesis(report="a second report"))
    with pytest.raises(RunAlreadyFinished):
        state.record_critique(critique(state.question, state.evidence))


def test_a_run_the_state_refused_to_extend_is_unchanged_by_the_attempt() -> None:
    state = run()
    before = state.model_dump(mode="json")

    with pytest.raises(RunAlreadyFinished):
        state.record_tool_call("retrieve", RetrieveRequest(question="anything"))

    assert state.model_dump(mode="json") == before
    assert verify_run(state).ok
