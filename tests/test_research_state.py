"""The state's two invariants: the step budget, and evidence counted once."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agentic_rag.agent import ResearchState, StepBudgetExceeded, StepRecord
from agentic_rag.tools import FakeRetrievalBackend, RetrieveRequest, RetrieveTool

QUESTION = "What does hybrid retrieval buy over dense retrieval alone?"
HYBRID_SUB_QUESTION = "hybrid retrieval dense sparse rankings"
OFF_CORPUS_SUB_QUESTION = "quarterly revenues in Patagonia"


def retrieve(state: ResearchState, sub_question: str, top_k: int = 5) -> StepRecord:
    tool = RetrieveTool(FakeRetrievalBackend())
    request = RetrieveRequest(question=sub_question, top_k=top_k)
    return state.record_retrieval(request, tool.run(request))


def test_a_fresh_state_has_its_whole_budget_and_no_evidence() -> None:
    state = ResearchState(question=QUESTION)

    assert state.steps_taken == 0
    assert state.budget_remaining == state.max_steps
    assert not state.budget_spent
    assert not state.has_evidence


def test_recording_a_retrieval_spends_a_step_and_keeps_its_evidence() -> None:
    state = ResearchState(question=QUESTION)

    record = retrieve(state, HYBRID_SUB_QUESTION)

    assert state.steps_taken == 1
    assert state.budget_remaining == state.max_steps - 1
    assert record.tool == "retrieve"
    assert record.request == HYBRID_SUB_QUESTION
    assert record.found_evidence
    assert state.evidence_ids == record.evidence_ids
    assert "hybrid-retrieval-1" in state.evidence_ids


def test_a_passage_retrieved_twice_is_kept_once() -> None:
    state = ResearchState(question=QUESTION)

    first = retrieve(state, HYBRID_SUB_QUESTION)
    retrieve(state, HYBRID_SUB_QUESTION)

    assert state.steps_taken == 2
    assert state.evidence_ids == first.evidence_ids
    assert len(state.evidence_ids) == len(set(state.evidence_ids))
    assert state.steps[1].evidence_ids == first.evidence_ids


def test_evidence_keeps_the_order_it_was_first_seen_in() -> None:
    state = ResearchState(question=QUESTION)

    retrieve(state, HYBRID_SUB_QUESTION, top_k=1)
    retrieve(state, "citation marker resolves to a retrieved chunk", top_k=1)

    assert state.evidence_ids == ("hybrid-retrieval-1", "citations-1")


def test_a_step_that_found_nothing_still_costs_a_step() -> None:
    state = ResearchState(question=QUESTION)

    record = retrieve(state, OFF_CORPUS_SUB_QUESTION)

    assert not record.found_evidence
    assert state.steps_taken == 1
    assert not state.has_evidence


def test_the_budget_is_enforced_by_the_state_not_by_the_caller() -> None:
    state = ResearchState(question=QUESTION, max_steps=1)

    retrieve(state, HYBRID_SUB_QUESTION)

    assert state.budget_spent
    with pytest.raises(StepBudgetExceeded, match="must answer or refuse"):
        retrieve(state, HYBRID_SUB_QUESTION)
    assert state.steps_taken == 1


def test_a_step_record_cannot_be_rewritten_after_the_fact() -> None:
    state = ResearchState(question=QUESTION)
    record = retrieve(state, HYBRID_SUB_QUESTION)

    with pytest.raises(ValidationError):
        record.request = "a different sub-question"


@pytest.mark.parametrize("kwargs", [{"question": ""}, {"question": QUESTION, "max_steps": 0}])
def test_a_state_that_could_not_terminate_is_rejected(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ResearchState(**kwargs)
