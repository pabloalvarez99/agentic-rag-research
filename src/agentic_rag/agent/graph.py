"""The loop: plan, then retrieve and critique until the run must stop.

The state machine is written as an ordinary bounded loop over thin nodes.
Two independent bounds guarantee termination, and both are load-bearing:

* **The step budget**, enforced inside :class:`~agentic_rag.agent.state.ResearchState`
  rather than by this loop's condition.
* **No sub-question is retrieved for twice.** Every follow-up a critique proposes
  is checked against what has already been requested.
* **Per-tool max_calls** (retrieve, search_notes, lexicon). Exhaustion is a typed
  stop (``tool_budget_spent``), never a hang.

Only ``critique`` can end the loop on success.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping

from agentic_rag.agent.critic import Critique, critique
from agentic_rag.agent.planner import plan_question
from agentic_rag.agent.state import (
    DEFAULT_MAX_STEPS,
    ResearchState,
    ResearchStatus,
    StopReason,
    TraceListener,
    default_max_tool_calls,
)
from agentic_rag.agent.synthesizer import synthesize
from agentic_rag.tools.lexicon import LexiconRequest, LexiconTool
from agentic_rag.tools.retrieve import (
    DEFAULT_TOP_K,
    RetrieveRequest,
    RetrieveTool,
    build_retrieve_tool,
)
from agentic_rag.tools.search_notes import SearchNotesRequest, SearchNotesTool

DEFAULT_NOTES_TOOL = SearchNotesTool()
"""Stateless free-path tool used when the critic requests a note review."""

DEFAULT_LEXICON_TOOL = LexiconTool()
"""Fixture lexicon tool — third free-path tool, no network."""


def decide_outcome(
    *,
    sufficient: bool,
    has_evidence: bool,
    budget_spent: bool,
    tool_budget_spent: bool = False,
) -> tuple[ResearchStatus, StopReason]:
    """Return the terminal status and the reason for it.

    Written as a pure function of booleans because the order of these tests *is*
    the policy. Reading top to bottom:

    * Sufficient evidence answers, whatever the budget did.
    * A run that retrieved nothing refuses, even if it had steps left.
    * A run that hit a per-tool max_calls ceiling reports ``tool_budget_spent``.
    * A run that gathered evidence, never reached sufficiency, and spent its
      global step budget reports ``budget_spent``.
    * Otherwise thin evidence with steps left is ``insufficient_evidence``.
    """
    if sufficient:
        return ResearchStatus.DONE, "evidence_sufficient"
    if not has_evidence:
        return ResearchStatus.REFUSED, "no_evidence"
    if tool_budget_spent:
        return ResearchStatus.BUDGET_EXHAUSTED, "tool_budget_spent"
    if budget_spent:
        return ResearchStatus.BUDGET_EXHAUSTED, "budget_spent"
    return ResearchStatus.REFUSED, "insufficient_evidence"


def plan_node(state: ResearchState) -> None:
    """Turn the question into the plan the loop will work through."""
    state.record_plan(plan_question(state.question))


def retrieve_node(state: ResearchState, tool: RetrieveTool, sub_question: str, top_k: int) -> None:
    """Spend one step retrieving for ``sub_question``, absorb it, and note what it says."""
    request = RetrieveRequest(question=sub_question, top_k=top_k)
    state.record_tool_call(tool.name, request)
    result = tool.run(request)
    state.record_retrieval(request, result)
    for passage in result.passages:
        state.record_note_from_passage(passage)


def critique_node(state: ResearchState) -> Critique:
    """Judge the notes gathered so far and record the verdict."""
    verdict = critique(
        state.question,
        state.notes,
        unanswered=state.unanswered_sub_questions,
    )
    state.record_critique(verdict)
    return verdict


def search_notes_node(state: ResearchState, tool: SearchNotesTool) -> None:
    """Rank the run's own notes when retrieval capacity remains, without adding evidence."""
    request = SearchNotesRequest(question=state.question, notes=tuple(state.notes))
    state.record_notes_search_call(request)
    state.record_notes_search(request, tool.run(request))


def lexicon_node(state: ResearchState, tool: LexiconTool, term: str) -> None:
    """Look up ``term`` in the fixture lexicon and record the call."""
    request = LexiconRequest(term=term)
    state.record_lexicon_call(request)
    state.record_lexicon(request, tool.run(request))


def finish_node(
    state: ResearchState,
    *,
    sufficient: bool,
    tool_budget_spent: bool = False,
) -> None:
    """Compose the report the outcome calls for and close the run."""
    status, reason = decide_outcome(
        sufficient=sufficient,
        has_evidence=state.has_evidence,
        budget_spent=state.budget_spent,
        tool_budget_spent=tool_budget_spent,
    )
    state.record_synthesis(
        synthesize(
            state.question,
            state.evidence,
            gaps=state.gaps,
            partial=status is ResearchStatus.BUDGET_EXHAUSTED,
            refused=status is ResearchStatus.REFUSED,
        )
    )
    state.finish(status, reason)


def run_research(
    question: str,
    *,
    tool: RetrieveTool | None = None,
    notes_tool: SearchNotesTool | None = DEFAULT_NOTES_TOOL,
    lexicon_tool: LexiconTool | None = DEFAULT_LEXICON_TOOL,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_tool_calls: Mapping[str, int] | None = None,
    top_k: int = DEFAULT_TOP_K,
    listener: TraceListener | None = None,
) -> ResearchState:
    """Research ``question`` under step and per-tool budgets; return finished state.

    Args:
        question: The research question.
        tool: The retrieve tool. Default free path contacts nothing unless
            ``PRODUCTION_RAG_URL`` is set via the library builder.
        notes_tool: Optional deterministic notes search. Pass ``None`` to disable.
        lexicon_tool: Optional fixture lexicon. Pass ``None`` to disable.
        max_steps: Hard cap on retrieval steps (also default retrieve max_calls).
        max_tool_calls: Optional overrides for per-tool caps.
        top_k: Passages one retrieval step may return.
        listener: Called with each trace event as it is recorded.

    Returns:
        The state, always with a terminal status, a report, and a trace ending in ``stop``.
    """
    caps = default_max_tool_calls(max_steps)
    if max_tool_calls:
        caps.update({name: int(value) for name, value in max_tool_calls.items()})
    state = ResearchState(question=question, max_steps=max_steps, max_tool_calls=caps)
    if listener is not None:
        state.subscribe(listener)
    retriever = build_retrieve_tool() if tool is None else tool

    plan_node(state)
    pending: deque[str] = deque(state.plan)
    requested: set[str] = set()
    sufficient = False
    hit_tool_budget = False
    lexicon_used_terms: set[str] = set()

    while pending and not state.budget_spent:
        if state.remaining_tool_calls(RetrieveTool.name) <= 0:
            hit_tool_budget = True
            break

        sub_question = pending.popleft()
        folded = sub_question.casefold()
        if folded in requested:
            continue
        requested.add(folded)

        retrieve_node(state, retriever, sub_question, top_k)
        verdict = critique_node(state)

        if (
            not verdict.sufficient
            and lexicon_tool is not None
            and state.remaining_tool_calls(LexiconTool.name) > 0
        ):
            for gap in verdict.gaps:
                if gap.kind != "uncovered_terms" or not gap.follow_up:
                    continue
                term = gap.follow_up.strip()
                key = term.casefold()
                if not term or key in lexicon_used_terms:
                    continue
                lexicon_used_terms.add(key)
                lexicon_node(state, lexicon_tool, term)
                break
        elif (
            not verdict.sufficient
            and lexicon_tool is not None
            and state.remaining_tool_calls(LexiconTool.name) <= 0
            and any(gap.kind == "uncovered_terms" for gap in verdict.gaps)
            and LexiconTool.name in state.max_tool_calls
            and state.max_tool_calls[LexiconTool.name] == 0
        ):
            # Explicit zero lexicon budget while a lookup would have been attempted.
            hit_tool_budget = True
            break

        if verdict.sufficient:
            if (
                verdict.requested_tool == SearchNotesTool.name
                and notes_tool is not None
                and not state.budget_spent
                and state.remaining_tool_calls(SearchNotesTool.name) > 0
            ):
                search_notes_node(state, notes_tool)
            elif (
                verdict.requested_tool == SearchNotesTool.name
                and notes_tool is not None
                and not state.budget_spent
                and state.remaining_tool_calls(SearchNotesTool.name) <= 0
            ):
                hit_tool_budget = True
            sufficient = True
            break

        queued = {candidate.casefold() for candidate in pending}
        for gap in verdict.gaps:
            follow_up = gap.follow_up
            if follow_up is None:
                continue
            key = follow_up.casefold()
            if key in requested or key in queued:
                continue
            pending.append(follow_up)
            queued.add(key)

    finish_node(state, sufficient=sufficient, tool_budget_spent=hit_tool_budget)
    return state
