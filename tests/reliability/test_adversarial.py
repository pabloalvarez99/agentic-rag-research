"""The matrix: inputs and backends chosen to break one assumption each.

The loop's own tests answer "does it work". These answer "what does it do when
the thing it depends on does not". Every case ends the same way — a terminal
status, a report, a trace whose last event is `stop`, and a verification with no
violations — because that is the claim: a bounded engine has no inputs that leave
it running, and none that leave it lying about what it did.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentic_rag.agent import (
    SUFFICIENT_SCORE,
    ResearchState,
    ResearchStatus,
    critique,
    run_research,
)
from agentic_rag.agent.synthesizer import SNIPPET_CHARS
from agentic_rag.tools import (
    DEFAULT_CORPUS,
    Document,
    FakeRetrievalBackend,
    Passage,
    RetrieveTool,
)
from agentic_rag.verification import verify_run
from reliability.backends import FailingBackend, StaticBackend, corpus
from reliability.generation import run_seeded, seeded_case

SEEDS = tuple(range(1, 61))

CHUNKING = "How does chunking work?"
TWO_STEP = "Explain chunking in detail for the record and explain refusal policy in detail as well"
OFF_CORPUS = "What were the quarterly revenues in Patagonia?"


def assert_sound(state: ResearchState) -> None:
    """Assert the things every finished run must satisfy, whatever it met."""
    report = verify_run(state)
    assert report.ok, report.summary()
    assert state.status.is_terminal
    assert state.stop_reason is not None
    assert state.report
    assert state.trace[-1].event == "stop"
    assert state.steps_taken <= state.max_steps


# --- what a backend can return ------------------------------------------------


def test_a_backend_that_returns_nothing_at_all_refuses() -> None:
    state = run_research(CHUNKING, tool=RetrieveTool(StaticBackend()), max_steps=4)

    assert state.status is ResearchStatus.REFUSED
    assert state.stop_reason == "no_evidence"
    assert not state.has_evidence
    assert_sound(state)


def test_a_backend_that_repeats_one_chunk_counts_it_once() -> None:
    duplicate = Passage(
        chunk_id="dup-1", source_path="docs/dup.md", text="Chunking splits.", rank=1
    )
    backend = StaticBackend([duplicate, duplicate, duplicate])

    state = run_research(CHUNKING, tool=RetrieveTool(backend), max_steps=4, top_k=5)

    assert state.evidence_ids == ("dup-1",)
    assert state.steps[0].evidence_ids == ("dup-1", "dup-1", "dup-1")
    assert [citation.chunk_id for citation in state.citations] == ["dup-1"]
    assert_sound(state)


def test_a_backend_that_answers_every_sub_question_identically_still_terminates() -> None:
    passage = Passage(chunk_id="same-1", source_path="docs/same.md", text="Anything.", rank=1)

    state = run_research(TWO_STEP, tool=RetrieveTool(StaticBackend([passage])), max_steps=20)

    assert state.steps_taken <= state.max_steps
    assert_sound(state)


def test_an_empty_corpus_is_not_a_failure() -> None:
    state = run_research(CHUNKING, tool=RetrieveTool(FakeRetrievalBackend([])), max_steps=3)

    assert state.status is ResearchStatus.REFUSED
    assert not state.has_tool_failure, "finding nothing is an answer, not a failure"
    assert_sound(state)


# --- repetition ---------------------------------------------------------------


@pytest.mark.parametrize("question", [CHUNKING, TWO_STEP, OFF_CORPUS])
@pytest.mark.parametrize("max_steps", [1, 4, 20])
def test_no_sub_question_is_ever_retrieved_twice(question: str, max_steps: int) -> None:
    state = run_research(
        question,
        tool=RetrieveTool(FakeRetrievalBackend()),
        max_steps=max_steps,
        top_k=1,
    )

    asked = [request.casefold() for request in state.requested_sub_questions]
    assert len(set(asked)) == len(asked)
    assert_sound(state)


def test_a_plan_that_repeats_itself_is_planned_once() -> None:
    repeated = "How does chunking work and how does CHUNKING work and how does chunking work?"

    state = run_research(repeated, tool=RetrieveTool(FakeRetrievalBackend()), max_steps=4)

    assert len(state.plan) == len({item.casefold() for item in state.plan})
    assert_sound(state)


# --- the budget ---------------------------------------------------------------


@pytest.mark.parametrize("max_steps", [1, 20])
def test_the_extremes_of_the_budget_behave(max_steps: int) -> None:
    state = run_research(TWO_STEP, tool=RetrieveTool(FakeRetrievalBackend()), max_steps=max_steps)

    assert state.steps_taken <= max_steps
    assert_sound(state)


def test_a_generous_budget_stops_for_a_reason_that_is_not_the_budget() -> None:
    state = run_research(OFF_CORPUS, tool=RetrieveTool(FakeRetrievalBackend()), max_steps=20)

    assert state.budget_remaining > 0
    assert state.stop_reason != "budget_spent"
    assert_sound(state)


@pytest.mark.parametrize("max_steps", [0, 21, -1])
def test_a_budget_outside_the_allowed_range_is_refused_before_the_run_starts(
    max_steps: int,
) -> None:
    with pytest.raises(ValidationError):
        ResearchState(question=CHUNKING, max_steps=max_steps)


# --- the critic's threshold ---------------------------------------------------


def test_the_score_exactly_at_the_threshold_is_sufficient() -> None:
    passage = Passage(
        chunk_id="edge-1",
        source_path="docs/edge.md",
        text="Hybrid retrieval fuses two rankings.",
        rank=1,
    )

    verdict = critique("hybrid retrieval", [passage])

    assert verdict.score == SUFFICIENT_SCORE
    assert verdict.sufficient
    assert verdict.gaps == ()


def test_one_point_below_the_threshold_is_not() -> None:
    passage = Passage(
        chunk_id="edge-2",
        source_path="docs/edge.md",
        text="Hybrid fusion of two rankings.",
        rank=1,
    )

    verdict = critique("hybrid retrieval", [passage])

    assert verdict.score == SUFFICIENT_SCORE - 1
    assert not verdict.sufficient
    assert verdict.gaps


def test_a_question_with_no_scoring_terms_at_all_still_terminates() -> None:
    state = run_research("the and or?", tool=RetrieveTool(FakeRetrievalBackend()), max_steps=3)

    assert_sound(state)


# --- oversized input ----------------------------------------------------------


def test_a_passage_far_longer_than_the_snippet_is_cut_at_a_word_boundary() -> None:
    body = "Chunking " + "splits a document into pieces " * 2_000
    state = run_research(
        CHUNKING,
        tool=RetrieveTool(FakeRetrievalBackend(corpus(body))),
        max_steps=2,
    )
    snippet = state.citations[0].snippet
    assert snippet is not None

    assert len(snippet) <= SNIPPET_CHARS + 3
    assert snippet.endswith("...")
    assert not snippet.removesuffix("...").endswith(" ")
    assert_sound(state)


def test_a_long_question_that_still_fits_the_tool_runs_normally() -> None:
    question = "How does chunking work " + "in a very long question " * 200
    assert len(question) < 8_000

    state = run_research(question, tool=RetrieveTool(FakeRetrievalBackend()), max_steps=3)

    assert_sound(state)


def test_a_sub_question_larger_than_the_tool_accepts_fails_loudly() -> None:
    question = "chunking " * 2_000
    assert len(question) > 8_000

    with pytest.raises(ValidationError, match="question"):
        run_research(question, tool=RetrieveTool(FakeRetrievalBackend()), max_steps=2)


# --- failures -----------------------------------------------------------------


@pytest.mark.parametrize("max_steps", [1, 2, 20])
def test_a_backend_that_always_fails_degrades_once_whatever_the_budget(max_steps: int) -> None:
    backend = FailingBackend(fail_from=1)

    state = run_research(TWO_STEP, tool=RetrieveTool(backend), max_steps=max_steps)

    assert backend.calls == 1
    assert state.status is ResearchStatus.DEGRADED
    assert state.steps_taken == 1
    assert_sound(state)


@pytest.mark.parametrize("fail_from", [1, 2, 3])
def test_a_failure_at_any_point_leaves_a_run_that_verifies(fail_from: int) -> None:
    backend = FailingBackend(fail_from=fail_from, delegate=FakeRetrievalBackend(DEFAULT_CORPUS))

    state = run_research(TWO_STEP, tool=RetrieveTool(backend), max_steps=20)

    assert_sound(state)
    if backend.calls >= fail_from:
        assert state.status is ResearchStatus.DEGRADED


def test_two_identical_failing_runs_are_byte_identical() -> None:
    first = run_research(TWO_STEP, tool=RetrieveTool(FailingBackend()), max_steps=4)
    second = run_research(TWO_STEP, tool=RetrieveTool(FailingBackend()), max_steps=4)

    assert first.model_dump() == second.model_dump()


# --- generated cases ----------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_a_generated_run_holds_every_invariant(seed: int) -> None:
    assert_sound(run_seeded(seed))


@pytest.mark.parametrize("seed", SEEDS[:12])
def test_a_generated_run_is_the_same_run_every_time(seed: int) -> None:
    assert run_seeded(seed).model_dump() == run_seeded(seed).model_dump()


def test_the_generated_cases_are_varied_enough_to_be_worth_running() -> None:
    states = [run_seeded(seed) for seed in SEEDS]

    assert len({state.status for state in states}) >= 2
    assert len({state.steps_taken for state in states}) >= 2
    assert any(state.has_evidence for state in states)
    assert any(not state.has_evidence for state in states)


def test_a_generated_case_depends_on_nothing_but_its_seed() -> None:
    assert seeded_case(7) == seeded_case(7)
    assert seeded_case(7) != seeded_case(8)


def test_generated_corpora_really_do_carry_the_text_that_breaks_reports() -> None:
    documents: list[Document] = [
        document for seed in SEEDS for document in seeded_case(seed).documents
    ]
    joined = "".join(document.text for document in documents)

    assert "\x1b" in joined, "the generator must produce control characters to be worth running"
    assert "[3]" in joined, "and marker shapes"
    assert "再ランキング" in joined
