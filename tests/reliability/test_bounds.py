"""How big a run can get, proved by counting rather than by timing.

A bound asserted with a stopwatch is a bound that fails on a loaded machine and
passes on a fast one, which makes it evidence about the runner rather than about
the code. Everything here counts events, steps and passages — the quantities the
budget is actually a bound on.

The claim is two bounds, and the second is the interesting one:

* `len(trace) <= 3 * max_steps + 3`. Three fixed events (`plan_created`,
  `synthesize`, `stop`) and at most three per step (`tool_call`, one of
  `tool_result`/`tool_error`, `critique`).
* No sub-question is retrieved for twice, so the work queue strictly shrinks and
  a run terminates whether or not the budget ever binds. That is what keeps a
  generous budget from turning every run into `budget_exhausted`.
"""

from __future__ import annotations

import pytest

from agentic_rag.agent import ResearchState, ResearchStatus, run_research
from agentic_rag.tools import DEFAULT_CORPUS, FakeRetrievalBackend, RetrieveTool
from agentic_rag.verification import verify_run
from reliability.backends import FailingBackend, ThinBackend, corpus
from reliability.generation import run_seeded, seeded_case

BUDGETS = tuple(range(1, 21))

QUESTIONS = (
    "How does chunking work?",
    "Explain chunking in detail for the record and explain refusal policy in detail as well",
    "What were the quarterly revenues in Patagonia?",
    "How does hybrid retrieval work and then how does reranking work and then citations?",
)

FIXED_EVENTS = 3
"""plan_created, synthesize, stop — recorded once each by every finished run."""

EVENTS_PER_STEP = 3
"""tool_call, one of tool_result / tool_error, and at most one critique."""


def trace_bound(max_steps: int) -> int:
    return EVENTS_PER_STEP * max_steps + FIXED_EVENTS


def run(question: str, max_steps: int) -> ResearchState:
    return run_research(
        question,
        tool=RetrieveTool(FakeRetrievalBackend()),
        max_steps=max_steps,
        top_k=1,
    )


@pytest.mark.parametrize("question", QUESTIONS)
@pytest.mark.parametrize("max_steps", BUDGETS)
def test_the_trace_stays_inside_three_events_per_step_plus_three(
    question: str,
    max_steps: int,
) -> None:
    state = run(question, max_steps)

    assert len(state.trace) <= trace_bound(max_steps)
    assert state.steps_taken <= max_steps


@pytest.mark.parametrize("seed", range(1, 41))
def test_a_generated_run_stays_inside_the_same_bound(seed: int) -> None:
    case = seeded_case(seed)

    state = run_seeded(seed)

    assert len(state.trace) <= trace_bound(case.max_steps)


@pytest.mark.parametrize("question", QUESTIONS)
def test_a_larger_budget_never_shortens_a_trace_and_never_outgrows_the_bound(
    question: str,
) -> None:
    lengths = [len(run(question, max_steps).trace) for max_steps in BUDGETS]

    assert lengths == sorted(lengths), "a bigger budget cannot produce a shorter run"
    assert all(
        length <= trace_bound(max_steps) for length, max_steps in zip(lengths, BUDGETS, strict=True)
    )


@pytest.mark.parametrize("question", QUESTIONS)
def test_doubling_the_budget_does_not_more_than_double_the_trace(question: str) -> None:
    for max_steps in (1, 2, 5, 10):
        small = len(run(question, max_steps).trace)
        large = len(run(question, max_steps * 2).trace)

        assert large <= 2 * small + FIXED_EVENTS, f"growth is not linear at {max_steps}"


@pytest.mark.parametrize("max_steps", BUDGETS)
def test_a_degraded_run_is_shorter_than_the_bound_because_it_stops(max_steps: int) -> None:
    state = run_research(
        QUESTIONS[1],
        tool=RetrieveTool(FailingBackend(fail_from=1)),
        max_steps=max_steps,
    )

    assert len(state.trace) == 5, "plan, call, error, synthesise, stop"
    assert len(state.trace) <= trace_bound(max_steps)


# --- per-step accounting ------------------------------------------------------


@pytest.mark.parametrize("question", QUESTIONS)
@pytest.mark.parametrize("max_steps", [1, 3, 7, 20])
def test_every_step_is_one_call_and_one_outcome(question: str, max_steps: int) -> None:
    state = run(question, max_steps)
    events = [event.event for event in state.trace]

    assert events.count("tool_call") == state.steps_taken
    assert events.count("tool_result") + events.count("tool_error") == state.steps_taken
    assert events.count("critique") <= state.steps_taken
    assert events.count("synthesize") == 1
    assert events.count("stop") == 1


@pytest.mark.parametrize("question", QUESTIONS)
@pytest.mark.parametrize("max_steps", [1, 4, 20])
def test_evidence_can_never_outgrow_the_corpus(question: str, max_steps: int) -> None:
    state = run(question, max_steps)

    assert len(state.evidence) <= len(DEFAULT_CORPUS)
    assert len(state.citations) == len(state.evidence)


# --- termination without the budget ------------------------------------------


@pytest.mark.parametrize("question", QUESTIONS)
def test_a_run_terminates_because_the_queue_empties_not_because_time_runs_out(
    question: str,
) -> None:
    state = run(question, 20)

    asked = [request.casefold() for request in state.requested_sub_questions]
    assert len(set(asked)) == len(asked)
    assert state.budget_remaining > 0
    assert state.stop_reason != "budget_spent"


def test_a_backend_that_never_satisfies_the_critic_still_stops() -> None:
    state = run_research(QUESTIONS[3], tool=RetrieveTool(ThinBackend()), max_steps=20)

    assert state.status is not ResearchStatus.RUNNING
    assert state.steps_taken <= state.max_steps
    assert verify_run(state).ok


# --- determinism --------------------------------------------------------------


@pytest.mark.parametrize("question", QUESTIONS)
@pytest.mark.parametrize("max_steps", [1, 4, 20])
def test_the_same_run_twice_is_the_same_dump_twice(question: str, max_steps: int) -> None:
    assert run(question, max_steps).model_dump() == run(question, max_steps).model_dump()


def test_a_run_over_awkward_text_is_still_reproducible() -> None:
    documents = corpus(
        "Chunking \x1b[31m splits [2] a document — 再ランキング — into pieces 🧭.",
        "Refusal\x00names the gap that chunking left.",
    )

    def once() -> ResearchState:
        return run_research(
            "How does chunking work and how does refusal work in a question long enough to split",
            tool=RetrieveTool(FakeRetrievalBackend(documents)),
            max_steps=4,
        )

    assert once().model_dump() == once().model_dump()
    assert verify_run(once()).ok
