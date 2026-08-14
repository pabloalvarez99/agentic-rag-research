"""The three pure components the loop wires together, tested without the loop."""

from __future__ import annotations

import pytest

from agentic_rag.agent import (
    MAX_SUB_QUESTIONS,
    SHORT_QUESTION_CHARS,
    SUFFICIENT_SCORE,
    Gap,
    critique,
    decide_outcome,
    plan_question,
    synthesize,
)
from agentic_rag.agent.state import ResearchStatus
from agentic_rag.tools import Passage

SHORT = "What does hybrid retrieval buy over dense retrieval alone?"
COMPOUND = (
    "How does chunking work and what happens when a citation marker resolves to nothing "
    "then how does refusal work?"
)


def passage(chunk_id: str, text: str, rank: int = 1) -> Passage:
    return Passage(chunk_id=chunk_id, source_path="docs/x.md", text=text, rank=rank)


# --- planner ----------------------------------------------------------------


def test_a_short_question_is_one_sub_question() -> None:
    assert len(SHORT) < SHORT_QUESTION_CHARS
    assert plan_question(SHORT) == [SHORT]


def test_a_compound_question_splits_on_the_joins_it_was_written_with() -> None:
    assert plan_question(COMPOUND) == [
        "How does chunking work",
        "what happens when a citation marker resolves to nothing",
        "how does refusal work",
    ]


def test_the_plan_is_capped_so_it_cannot_outlast_a_normal_budget() -> None:
    question = " and ".join(f"what is topic number {index}" for index in range(8))

    plan = plan_question(question)

    assert len(plan) == MAX_SUB_QUESTIONS
    assert plan[0] == "what is topic number 0"


def test_planning_is_deterministic() -> None:
    assert plan_question(COMPOUND) == plan_question(COMPOUND)


def test_fragments_carrying_no_scoring_term_are_not_worth_a_step() -> None:
    question = "What is reciprocal rank fusion and, then, how exactly is it used in this pipeline?"

    plan = plan_question(question)

    assert len(question) >= SHORT_QUESTION_CHARS
    assert plan == ["What is reciprocal rank fusion", "how exactly is it used in this pipeline"]


def test_a_long_question_that_splits_into_nothing_falls_back_to_itself() -> None:
    question = "and then " * 12

    assert len(question) >= SHORT_QUESTION_CHARS
    assert plan_question(question) == [question.strip()]


# --- critic -----------------------------------------------------------------


def test_the_score_is_passages_plus_covered_question_terms() -> None:
    verdict = critique(
        "hybrid retrieval",
        [passage("a", "Hybrid retrieval fuses two rankings.")],
    )

    assert verdict.note_count == 1
    assert verdict.keyword_overlap == 2
    assert verdict.score == 3
    assert verdict.sufficient
    assert verdict.gaps == ()


def test_the_critic_requests_note_search_only_when_multiple_notes_are_sufficient() -> None:
    one = critique("hybrid retrieval", [passage("a", "Hybrid retrieval fuses rankings.")])
    many = critique(
        "hybrid retrieval",
        [passage("a", "Hybrid search."), passage("b", "Retrieval fuses rankings.")],
    )

    assert one.requested_tool is None
    assert many.sufficient
    assert many.requested_tool == "search_notes"


def test_evidence_below_the_threshold_is_not_sufficient() -> None:
    verdict = critique("hybrid retrieval reranking", [passage("a", "Hybrid search.")])

    assert verdict.score < SUFFICIENT_SCORE
    assert not verdict.sufficient


def test_a_high_score_without_a_single_passage_is_still_not_sufficient() -> None:
    verdict = critique("hybrid retrieval reranking chunking citations", [])

    assert verdict.note_count == 0
    assert not verdict.sufficient


def test_gaps_name_the_sub_question_that_returned_nothing() -> None:
    verdict = critique("hybrid retrieval", [], unanswered=["hybrid retrieval dense"])

    details = [gap.detail for gap in verdict.gaps]
    assert any("hybrid retrieval dense" in detail for detail in details)
    assert {gap.kind for gap in verdict.gaps} == {"unanswered_sub_question", "uncovered_terms"}


def test_a_sub_question_that_found_nothing_is_never_proposed_again() -> None:
    verdict = critique("hybrid retrieval", [], unanswered=["hybrid retrieval"])

    unanswered_gaps = [gap for gap in verdict.gaps if gap.kind == "unanswered_sub_question"]
    assert unanswered_gaps
    assert all(gap.follow_up is None for gap in unanswered_gaps)


def test_uncovered_terms_are_named_and_become_a_follow_up() -> None:
    verdict = critique("hybrid retrieval and reranking", [passage("a", "Hybrid search only.")])

    uncovered = next(gap for gap in verdict.gaps if gap.kind == "uncovered_terms")
    assert "reranking" in uncovered.detail
    assert "retrieval" in uncovered.detail
    assert uncovered.follow_up == "reranking retrieval"


def test_evidence_that_covers_every_term_but_stays_thin_says_so() -> None:
    verdict = critique("chunking", [passage("a", "Chunking splits a document.")])

    assert not verdict.sufficient
    assert [gap.kind for gap in verdict.gaps] == ["thin_evidence"]
    assert "below the threshold" in verdict.gaps[0].detail


# --- outcome policy ---------------------------------------------------------


@pytest.mark.parametrize(
    ("sufficient", "has_evidence", "budget_spent", "expected"),
    [
        (True, True, False, (ResearchStatus.DONE, "evidence_sufficient")),
        (True, True, True, (ResearchStatus.DONE, "evidence_sufficient")),
        (False, False, False, (ResearchStatus.REFUSED, "no_evidence")),
        (False, False, True, (ResearchStatus.REFUSED, "no_evidence")),
        (False, True, True, (ResearchStatus.BUDGET_EXHAUSTED, "budget_spent")),
        (False, True, False, (ResearchStatus.REFUSED, "insufficient_evidence")),
    ],
)
def test_the_terminal_status_is_a_function_of_three_facts(
    sufficient: bool,
    has_evidence: bool,
    budget_spent: bool,
    expected: tuple[ResearchStatus, str],
) -> None:
    assert (
        decide_outcome(
            sufficient=sufficient,
            has_evidence=has_evidence,
            budget_spent=budget_spent,
        )
        == expected
    )


# --- synthesizer ------------------------------------------------------------


def test_markers_follow_the_order_evidence_was_first_seen_in() -> None:
    synthesis = synthesize(
        "q",
        [passage("first", "First passage."), passage("second", "Second passage.", rank=2)],
    )

    assert "- First passage. [1]" in synthesis.report
    assert "- Second passage. [2]" in synthesis.report
    assert [(c.marker, c.chunk_id) for c in synthesis.citations] == [(1, "first"), (2, "second")]


def test_a_report_prints_no_sentence_that_is_not_a_retrieved_passage() -> None:
    text = "Hybrid retrieval fuses two rankings."
    synthesis = synthesize("q", [passage("a", text)])

    findings = [line for line in synthesis.report.splitlines() if line.startswith("- ")]
    assert findings == [f"- {text} [1]"]


def test_a_partial_report_still_prints_what_it_never_closed() -> None:
    synthesis = synthesize(
        "q",
        [passage("a", "Only this.")],
        gaps=[Gap(kind="uncovered_terms", detail="no retrieved passage mentions: reranking")],
        partial=True,
    )

    assert "Status: partial." in synthesis.report
    assert "no retrieved passage mentions: reranking" in synthesis.report
    assert len(synthesis.citations) == 1


def test_a_refusal_with_no_evidence_cites_nothing() -> None:
    synthesis = synthesize("q", [], gaps=[Gap(kind="no_evidence", detail="nothing")], refused=True)

    assert "Refused: nothing was retrieved" in synthesis.report
    assert synthesis.citations == ()


def test_a_long_passage_is_cut_at_a_word_boundary() -> None:
    synthesis = synthesize("q", [passage("a", "word " * 200)])

    finding = next(line for line in synthesis.report.splitlines() if line.startswith("- "))
    assert finding.endswith("... [1]")
    assert "wor... " not in finding
