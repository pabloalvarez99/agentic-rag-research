"""Third tool (lexicon) and per-tool max_calls typed stops."""

from __future__ import annotations

import pytest

from agentic_rag.agent import (
    ResearchStatus,
    ToolBudgetExceeded,
    decide_outcome,
    run_research,
)
from agentic_rag.agent.state import ResearchState
from agentic_rag.tools import FakeRetrievalBackend, LexiconRequest, LexiconTool, RetrieveTool
from agentic_rag.tools.retrieve import RetrieveRequest


def test_lexicon_returns_fixture_hits_without_network() -> None:
    result = LexiconTool().run(LexiconRequest(term="reciprocal rank fusion"))
    assert result.backend == "fixture"
    assert result.entries
    assert all(entry.chunk_id for entry in result.entries)


def test_per_tool_budget_exhaustion_is_typed_not_a_hang() -> None:
    state = run_research(
        "How does the Reykjavik trampoline audit affect chunking?",
        tool=RetrieveTool(FakeRetrievalBackend()),
        max_steps=4,
        top_k=1,
        max_tool_calls={"retrieve": 1, "search_notes": 4, "lexicon": 2},
    )
    assert state.status is ResearchStatus.BUDGET_EXHAUSTED
    assert state.stop_reason == "tool_budget_spent"
    assert state.steps_taken == 1
    assert state.has_evidence
    assert any(
        event.event == "tool_call" and event.payload.get("tool") == "retrieve"
        for event in state.trace
    )


def test_consume_tool_budget_raises_when_spent() -> None:
    state = ResearchState(
        question="Why use citations?",
        max_steps=2,
        max_tool_calls={"retrieve": 0, "search_notes": 0, "lexicon": 0},
    )
    with pytest.raises(ToolBudgetExceeded):
        state.record_tool_call("retrieve", RetrieveRequest(question="x", top_k=1))


def test_decide_outcome_prefers_tool_budget_when_evidence_exists() -> None:
    assert decide_outcome(
        sufficient=False,
        has_evidence=True,
        budget_spent=False,
        tool_budget_spent=True,
    ) == (ResearchStatus.BUDGET_EXHAUSTED, "tool_budget_spent")
