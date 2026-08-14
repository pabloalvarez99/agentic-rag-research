"""The loop end to end: how it stops, what it cites, and what it records.

Every test runs against the committed in-process corpus. Nothing here opens a
socket, reads an environment variable, or needs a credential — the tool is
always constructed explicitly, so a `PRODUCTION_RAG_URL` left set in a shell
cannot change what these tests assert.
"""

from __future__ import annotations

import re

import pytest

from agentic_rag.agent import (
    ResearchState,
    ResearchStatus,
    RunAlreadyFinished,
    run_research,
)
from agentic_rag.tools import Document, FakeRetrievalBackend, RetrieveTool

ANSWERABLE = "What does hybrid retrieval buy over dense retrieval alone?"
COMPOUND = (
    "How does chunking work and what happens when a citation marker resolves to nothing "
    "then how does refusal work?"
)
OFF_CORPUS = "What were the quarterly revenues in Patagonia?"
THIN = "How does chunking work?"

MARKER = re.compile(r"\[(\d+)\]")


@pytest.fixture
def tool() -> RetrieveTool:
    return RetrieveTool(FakeRetrievalBackend())


def markers(report: str) -> list[int]:
    return [int(match) for match in MARKER.findall(report)]


def test_the_happy_path_answers_from_evidence_and_stops(tool: RetrieveTool) -> None:
    state = run_research(ANSWERABLE, tool=tool)

    assert state.status is ResearchStatus.DONE
    assert state.stop_reason == "evidence_sufficient"
    assert state.has_evidence
    assert state.gaps == []
    assert state.report is not None
    assert state.steps_taken < state.max_steps


def test_a_run_is_byte_identical_when_repeated(tool: RetrieveTool) -> None:
    first = run_research(COMPOUND, tool=tool)
    second = run_research(COMPOUND, tool=RetrieveTool(FakeRetrievalBackend()))

    assert first.trace == second.trace
    assert first.report == second.report
    assert first.model_dump() == second.model_dump()


def test_the_plan_is_recorded_before_any_tool_runs(tool: RetrieveTool) -> None:
    state = run_research(COMPOUND, tool=tool)

    assert state.trace[0].event == "plan_created"
    assert state.trace[0].payload["sub_questions"] == state.plan
    assert state.plan[0] == "How does chunking work"


def test_every_marker_in_the_report_resolves_to_retrieved_evidence(tool: RetrieveTool) -> None:
    state = run_research(ANSWERABLE, tool=tool)
    assert state.report is not None

    printed = markers(state.report)
    assert printed == [citation.marker for citation in state.citations]
    assert printed == list(range(1, len(state.evidence) + 1))
    for citation in state.citations:
        passage = state.evidence[citation.marker - 1]
        assert citation.chunk_id == passage.chunk_id
        assert citation.chunk_id in state.evidence_ids
        assert citation.source_path == passage.source_path
        assert citation.snippet is not None
        assert citation.snippet.split("...")[0] in " ".join(passage.text.split())


def test_a_passage_retrieved_by_two_sub_questions_is_cited_once(tool: RetrieveTool) -> None:
    overlapping = Document(
        chunk_id="shared-1",
        source_path="docs/shared.md",
        text="Chunking splits a document into pieces.",
    )
    state = run_research(
        "Explain chunking thoroughly and explain chunking in the Patagonia quarterly ledger",
        tool=RetrieveTool(FakeRetrievalBackend([overlapping])),
        max_steps=3,
        top_k=5,
    )

    assert state.steps_taken >= 2
    assert state.evidence_ids == ("shared-1",)
    assert [citation.chunk_id for citation in state.citations] == ["shared-1"]
    assert state.steps[0].evidence_ids == state.steps[1].evidence_ids


def test_a_run_that_retrieved_nothing_refuses_and_cites_nothing(tool: RetrieveTool) -> None:
    state = run_research(OFF_CORPUS, tool=tool, max_steps=3)

    assert state.status is ResearchStatus.REFUSED
    assert state.stop_reason == "no_evidence"
    assert state.citations == []
    assert state.report is not None
    assert markers(state.report) == []
    assert "Refused" in state.report


def test_a_refusal_names_the_sub_questions_that_found_nothing(tool: RetrieveTool) -> None:
    state = run_research(OFF_CORPUS, tool=tool, max_steps=3)
    assert state.report is not None

    details = [gap.detail for gap in state.gaps]
    assert any(OFF_CORPUS in detail for detail in details)
    assert any("patagonia" in detail for detail in details)
    for detail in details:
        assert detail in state.report


def test_a_budget_that_ends_early_reports_what_it_grounded(tool: RetrieveTool) -> None:
    state = run_research(THIN, tool=tool, max_steps=1, top_k=1)

    assert state.status is ResearchStatus.BUDGET_EXHAUSTED
    assert state.stop_reason == "budget_spent"
    assert state.steps_taken == state.max_steps
    assert state.report is not None
    assert "Status: partial." in state.report
    assert markers(state.report) == [citation.marker for citation in state.citations]
    assert state.gaps
    assert all(gap.detail in state.report for gap in state.gaps)


def test_thin_evidence_with_budget_left_refuses_rather_than_blaming_the_budget() -> None:
    backend = FakeRetrievalBackend(
        [Document(chunk_id="only-1", source_path="docs/x.md", text="Chunking.")]
    )

    state = run_research("chunking?", tool=RetrieveTool(backend), max_steps=5)

    assert state.status is ResearchStatus.REFUSED
    assert state.stop_reason == "insufficient_evidence"
    assert state.budget_remaining > 0
    assert state.report is not None
    assert state.citations, "a refusal still shows the evidence it did gather"


@pytest.mark.parametrize("question", [ANSWERABLE, COMPOUND, OFF_CORPUS, THIN])
@pytest.mark.parametrize("max_steps", [1, 2, 3, 5])
def test_the_budget_is_never_exceeded_whatever_the_question(
    tool: RetrieveTool,
    question: str,
    max_steps: int,
) -> None:
    state = run_research(question, tool=tool, max_steps=max_steps, top_k=1)

    assert state.steps_taken <= max_steps
    assert state.trace[-1].payload["steps_used"] == state.steps_taken
    assert state.status is not ResearchStatus.RUNNING


@pytest.mark.parametrize("question", [ANSWERABLE, COMPOUND, OFF_CORPUS, THIN])
def test_every_run_ends_with_a_stop_event_and_a_terminal_status(
    tool: RetrieveTool,
    question: str,
) -> None:
    state = run_research(question, tool=tool, max_steps=3)

    assert state.trace[-1].event == "stop"
    assert state.trace[-1].payload["status"] == state.status.value
    assert state.trace[-1].payload["reason"] == state.stop_reason
    assert state.is_finished
    assert [event.event for event in state.trace].count("stop") == 1


def test_the_trace_records_every_stage_in_order(tool: RetrieveTool) -> None:
    state = run_research(ANSWERABLE, tool=tool)

    assert [event.event for event in state.trace] == [
        "plan_created",
        "tool_call",
        "tool_result",
        *["note_added"] * len(state.notes),
        "critique",
        "tool_call",
        "tool_result",
        "synthesize",
        "stop",
    ]
    call, result = state.trace[1], state.trace[2]
    assert call.payload["tool"] == "retrieve"
    assert result.payload["backend"] == "fake"
    assert result.payload["evidence_ids"] == list(state.evidence_ids)

    added = [event for event in state.trace if event.event == "note_added"]
    assert [event.payload["id"] for event in added] == list(state.note_ids)
    assert [event.payload["citation"] for event in added] == list(state.evidence_ids)
    assert all(event.payload["grounded"] is True for event in added)

    verdict = state.trace[3 + len(state.notes)]
    assert verdict.event == "critique"
    assert verdict.payload["score"] == verdict.payload["relevant_note_count"] + (
        verdict.payload["keyword_overlap"]
    )
    assert verdict.payload["note_count"] == len(state.notes)
    assert verdict.payload["grounded_note_count"] == len(state.grounded_notes)
    assert verdict.payload["sufficient"] is True
    assert verdict.payload["requested_tool"] == "search_notes"
    notes_call, notes_result = state.trace[4 + len(state.notes)], state.trace[5 + len(state.notes)]
    assert notes_call.payload["tool"] == "search_notes"
    assert notes_result.payload["backend"] == "in_process"
    assert notes_result.payload["inspected"] == len(state.notes)
    assert notes_result.payload["note_ids"]


def test_note_search_is_optional_and_stays_inside_the_step_budget(tool: RetrieveTool) -> None:
    with_notes = run_research(ANSWERABLE, tool=tool, max_steps=4)
    without_notes = run_research(ANSWERABLE, tool=tool, notes_tool=None, max_steps=4)
    no_room = run_research(ANSWERABLE, tool=tool, max_steps=1)

    assert any(event.payload.get("tool") == "search_notes" for event in with_notes.trace)
    assert all(event.payload.get("tool") != "search_notes" for event in without_notes.trace)
    assert all(event.payload.get("tool") != "search_notes" for event in no_room.trace)
    assert with_notes.steps_taken <= with_notes.max_steps


def test_the_trace_carries_no_wall_clock_field(tool: RetrieveTool) -> None:
    state = run_research(ANSWERABLE, tool=tool)

    assert all("ts" not in event.payload for event in state.trace)
    assert "ts" not in state.trace[0].model_dump()


def test_a_finished_run_records_no_further_work(tool: RetrieveTool) -> None:
    state = run_research(ANSWERABLE, tool=tool)

    with pytest.raises(RunAlreadyFinished):
        state.finish(ResearchStatus.DONE, "evidence_sufficient")
    with pytest.raises(RunAlreadyFinished):
        state.record_plan(["another plan"])


def test_a_non_terminal_status_cannot_close_a_run() -> None:
    state = ResearchState(question=ANSWERABLE)

    with pytest.raises(ValueError, match="not a terminal status"):
        state.finish(ResearchStatus.RUNNING, "evidence_sufficient")


def test_an_empty_plan_is_rejected() -> None:
    state = ResearchState(question=ANSWERABLE)

    with pytest.raises(ValueError, match="at least one sub-question"):
        state.record_plan([])
