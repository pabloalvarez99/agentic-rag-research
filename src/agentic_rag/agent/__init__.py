"""The agent loop and the state it carries.

M2 ships the whole loop as a library: ``plan_question``, ``critique``,
``synthesize``, and ``run_research`` wiring them together under the step budget
that :class:`ResearchState` enforces. The HTTP route and the CLI that expose it
arrive with M3 (``docs/architecture.md``).
"""

from __future__ import annotations

from agentic_rag.agent.critic import SUFFICIENT_SCORE, Critique, Gap, critique
from agentic_rag.agent.failures import TOOL_ERROR, ToolFailure, ToolFailureType, tool_failure
from agentic_rag.agent.graph import (
    critique_node,
    decide_outcome,
    finish_node,
    plan_node,
    retrieve_node,
    run_research,
)
from agentic_rag.agent.planner import MAX_SUB_QUESTIONS, SHORT_QUESTION_CHARS, plan_question
from agentic_rag.agent.state import (
    DEFAULT_MAX_STEPS,
    TERMINAL_STATUSES,
    ResearchState,
    ResearchStatus,
    RunAlreadyFinished,
    StepBudgetExceeded,
    StepRecord,
    StopReason,
    TraceEvent,
    TraceEventName,
)
from agentic_rag.agent.synthesizer import Citation, Synthesis, synthesize

__all__ = [
    "DEFAULT_MAX_STEPS",
    "MAX_SUB_QUESTIONS",
    "SHORT_QUESTION_CHARS",
    "SUFFICIENT_SCORE",
    "TERMINAL_STATUSES",
    "TOOL_ERROR",
    "Citation",
    "Critique",
    "Gap",
    "ResearchState",
    "ResearchStatus",
    "RunAlreadyFinished",
    "StepBudgetExceeded",
    "StepRecord",
    "StopReason",
    "Synthesis",
    "ToolFailure",
    "ToolFailureType",
    "TraceEvent",
    "TraceEventName",
    "critique",
    "critique_node",
    "decide_outcome",
    "finish_node",
    "plan_node",
    "plan_question",
    "retrieve_node",
    "run_research",
    "synthesize",
    "tool_failure",
]
