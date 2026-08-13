"""The documented rules and the implementation must describe the same loop."""

from __future__ import annotations

from pathlib import Path

import pytest
from spec_model import (
    MAX_SUB_QUESTIONS,
    SHORT_QUESTION_CHARS,
    SUFFICIENT_SCORE,
    decide,
    plan,
    predict,
    search,
)

from agentic_rag.agent import planner
from agentic_rag.agent.critic import SUFFICIENT_SCORE as IMPLEMENTED_SUFFICIENT_SCORE
from agentic_rag.agent.graph import decide_outcome
from agentic_rag.evals.dataset import EvalCase, read_cases
from agentic_rag.evals.runner import build_fixture_tool, default_runner
from agentic_rag.tools.retrieve import RetrieveRequest

DATASET = Path("data/eval/golden_research.jsonl")


@pytest.fixture(scope="module")
def cases() -> tuple[EvalCase, ...]:
    parsed, errors = read_cases(DATASET)
    assert not errors
    return parsed


def test_spec_constants_match_the_implementation() -> None:
    assert SHORT_QUESTION_CHARS == planner.SHORT_QUESTION_CHARS
    assert MAX_SUB_QUESTIONS == planner.MAX_SUB_QUESTIONS
    assert SUFFICIENT_SCORE == IMPLEMENTED_SUFFICIENT_SCORE


@pytest.mark.parametrize(
    ("sufficient", "has_evidence", "budget_spent"),
    [
        (sufficient, has_evidence, budget_spent)
        for sufficient in (True, False)
        for has_evidence in (True, False)
        for budget_spent in (True, False)
    ],
)
def test_outcome_table_agrees_on_every_combination(
    *, sufficient: bool, has_evidence: bool, budget_spent: bool
) -> None:
    status, reason = decide(
        sufficient=sufficient, has_evidence=has_evidence, budget_spent=budget_spent
    )
    implemented_status, implemented_reason = decide_outcome(
        sufficient=sufficient, has_evidence=has_evidence, budget_spent=budget_spent
    )
    assert (status, reason) == (implemented_status.value, implemented_reason)


def test_planner_agrees_on_every_golden_question(cases: tuple[EvalCase, ...]) -> None:
    for case in cases:
        assert list(plan(case.question)) == planner.plan_question(case.question), case.id


def test_fixture_ranking_agrees_on_every_golden_question(cases: tuple[EvalCase, ...]) -> None:
    tool = build_fixture_tool()
    for case in cases:
        predicted = [document.chunk_id for document in search(case.question, case.top_k)]
        result = tool.run(RetrieveRequest(question=case.question, top_k=case.top_k))
        assert predicted == [passage.chunk_id for passage in result.passages], case.id


def test_whole_loop_agrees_on_every_golden_question(cases: tuple[EvalCase, ...]) -> None:
    """The strongest form: run both over the dataset and compare outcome by outcome.

    A failure here is not a test to fix. It means ``docs/architecture.md`` and the
    code disagree about what the loop does, and one of the two has to change.
    """
    disagreements: list[str] = []
    for case in cases:
        expected = predict(case.question, max_steps=case.max_steps, top_k=case.top_k)
        state = default_runner(case.question, build_fixture_tool(), case.max_steps, case.top_k)
        actual = (
            state.status.value,
            state.stop_reason,
            state.steps_taken,
            tuple(state.evidence_ids),
        )
        wanted = (expected.status, expected.stop_reason, expected.steps, expected.evidence_ids)
        if actual != wanted:
            disagreements.append(f"{case.id}: spec says {wanted}, loop did {actual}")
    assert not disagreements, "\n".join(disagreements)
