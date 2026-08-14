"""The agent loop and the state it carries.

M2 ships the whole loop as a library: ``plan_question``, ``critique``,
``synthesize``, and ``run_research`` wiring them together under the step budget
that :class:`ResearchState` enforces. The HTTP route and the CLI that expose it
arrive with M3 (``docs/architecture.md``).
"""

from __future__ import annotations

from agentic_rag.agent.critic import SUFFICIENT_SCORE, Critique, Gap, critique
from agentic_rag.agent.graph import (
    critique_node,
    decide_outcome,
    finish_node,
    lexicon_node,
    plan_node,
    retrieve_node,
    run_research,
    search_notes_node,
)
from agentic_rag.agent.planner import MAX_SUB_QUESTIONS, SHORT_QUESTION_CHARS, plan_question
from agentic_rag.agent.state import (
    DEFAULT_LEXICON_MAX_CALLS,
    DEFAULT_MAX_STEPS,
    DEFAULT_SEARCH_NOTES_MAX_CALLS,
    TERMINAL_STATUSES,
    ResearchState,
    ResearchStatus,
    RunAlreadyFinished,
    StepBudgetExceeded,
    StepRecord,
    StopReason,
    ToolBudgetExceeded,
    TraceEvent,
    TraceEventName,
    default_max_tool_calls,
)
from agentic_rag.agent.synthesizer import Citation, Synthesis, synthesize
from agentic_rag.notes import Note, claim_from_text, note_from_passage, note_id

__all__ = [
    "DEFAULT_LEXICON_MAX_CALLS",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_SEARCH_NOTES_MAX_CALLS",
    "MAX_SUB_QUESTIONS",
    "SHORT_QUESTION_CHARS",
    "SUFFICIENT_SCORE",
    "TERMINAL_STATUSES",
    "Citation",
    "Critique",
    "Gap",
    "Note",
    "ResearchState",
    "ResearchStatus",
    "RunAlreadyFinished",
    "StepBudgetExceeded",
    "StepRecord",
    "StopReason",
    "Synthesis",
    "ToolBudgetExceeded",
    "TraceEvent",
    "TraceEventName",
    "claim_from_text",
    "critique",
    "critique_node",
    "decide_outcome",
    "default_max_tool_calls",
    "finish_node",
    "lexicon_node",
    "note_from_passage",
    "note_id",
    "plan_node",
    "plan_question",
    "retrieve_node",
    "run_research",
    "search_notes_node",
    "synthesize",
]
