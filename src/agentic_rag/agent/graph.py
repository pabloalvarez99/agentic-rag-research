"""The loop: plan, then retrieve and critique until the run must stop.

The state machine is written as an ordinary bounded loop over four thin nodes.
A graph library was considered and not used at this milestone: every node here
is a two-line call into a pure function that is already tested on its own, so a
framework would add a dependency, an import-time registry and a second place to
read the control flow, in exchange for a picture of a loop that fits on one
screen. The seam it would occupy is the node functions below, which take a state
and return nothing — adopting one later is a rewiring, not a rewrite. That
trade-off is recorded in ``docs/architecture.md``.

Two independent bounds guarantee termination, and both are load-bearing:

* **The step budget**, enforced inside :class:`~agentic_rag.agent.state.ResearchState`
  rather than by this loop's condition. A budget checked at the call site has as
  many rules as it has call sites.
* **No sub-question is retrieved for twice.** Every follow-up a critique proposes
  is checked against what has already been requested, so the queue strictly
  shrinks even when the budget is generous. Without it a gap that no retrieval
  can close would be re-issued until the budget ran out, and every run would
  report ``budget_exhausted`` regardless of why it really stopped.

Only ``critique`` can end the loop on success. ``plan`` cannot declare success
and ``retrieve`` cannot declare failure, so there is one place to audit when a
run ends wrongly.
"""

from __future__ import annotations

from collections import deque

from agentic_rag.agent.critic import Critique, critique
from agentic_rag.agent.planner import plan_question
from agentic_rag.agent.state import (
    DEFAULT_MAX_STEPS,
    ResearchState,
    ResearchStatus,
    StopReason,
)
from agentic_rag.agent.synthesizer import synthesize
from agentic_rag.tools.retrieve import (
    DEFAULT_TOP_K,
    RetrieveRequest,
    RetrieveTool,
    build_retrieve_tool,
)
from agentic_rag.tools.search_notes import SearchNotesRequest, SearchNotesTool

DEFAULT_NOTES_TOOL = SearchNotesTool()
"""Stateless free-path tool used when the critic requests a note review."""


def decide_outcome(
    *,
    sufficient: bool,
    has_evidence: bool,
    budget_spent: bool,
) -> tuple[ResearchStatus, StopReason]:
    """Return the terminal status and the reason for it.

    Written as a pure function of three booleans because the order of these
    tests *is* the policy, and a policy buried inside a loop is one that gets
    quietly reordered. Reading top to bottom:

    * Sufficient evidence answers, whatever the budget did.
    * A run that retrieved nothing refuses, even if it had steps left. There is
      no report to make partial.
    * A run that gathered evidence, never reached sufficiency, and spent its
      budget reports what it grounded and says the budget ended it.
    * A run that gathered evidence, never reached sufficiency and still has
      steps left has no action left to take: every follow-up is already
      retrieved for. Thin evidence that supports no answer is a refusal, and
      claiming the budget ended a run that stopped early would be a lie in the
      one field an operator would check first.

    Args:
        sufficient: The last critique found the evidence enough to answer from.
        has_evidence: At least one passage was gathered.
        budget_spent: The step budget is fully used.

    Returns:
        The terminal status and the closed-set reason recorded with it.
    """
    if sufficient:
        return ResearchStatus.DONE, "evidence_sufficient"
    if not has_evidence:
        return ResearchStatus.REFUSED, "no_evidence"
    if budget_spent:
        return ResearchStatus.BUDGET_EXHAUSTED, "budget_spent"
    return ResearchStatus.REFUSED, "insufficient_evidence"


def plan_node(state: ResearchState) -> None:
    """Turn the question into the plan the loop will work through."""
    state.record_plan(plan_question(state.question))


def retrieve_node(state: ResearchState, tool: RetrieveTool, sub_question: str, top_k: int) -> None:
    """Spend one step retrieving for ``sub_question``, absorb it, and note what it says.

    Writing the notes here rather than inside the state's retrieval bookkeeping keeps
    the two facts separate: the step spent a budget unit and returned these chunk ids,
    and the run then decided which claims it is relying on. A backend that returns a
    passage the run cannot take a claim from spends the step either way, and the trace
    shows both halves.
    """
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


def finish_node(state: ResearchState, *, sufficient: bool) -> None:
    """Compose the report the outcome calls for and close the run."""
    status, reason = decide_outcome(
        sufficient=sufficient,
        has_evidence=state.has_evidence,
        budget_spent=state.budget_spent,
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
    max_steps: int = DEFAULT_MAX_STEPS,
    top_k: int = DEFAULT_TOP_K,
) -> ResearchState:
    """Research ``question`` under a step budget and return the finished state.

    Args:
        question: The research question.
        tool: The retrieve tool to spend steps on. Omitted, the free path is
            built by :func:`~agentic_rag.tools.retrieve.build_retrieve_tool`,
            which contacts nothing unless ``PRODUCTION_RAG_URL`` is set.
        notes_tool: Optional deterministic tool for searching evidence already gathered.
            The critic requests it only after finding sufficient evidence, and it runs
            only when retrieval capacity remains. It is local post-processing rather than
            another retrieval step. Pass ``None`` to disable it.
        max_steps: Hard cap on tool calls, enforced by the state.
        top_k: Passages one retrieval step may return.

    Returns:
        The state, always with a terminal status, a report, and a trace whose
        last event is ``stop``.
    """
    state = ResearchState(question=question, max_steps=max_steps)
    retriever = build_retrieve_tool() if tool is None else tool

    plan_node(state)
    pending: deque[str] = deque(state.plan)
    requested: set[str] = set()
    sufficient = False

    while pending and not state.budget_spent:
        sub_question = pending.popleft()
        folded = sub_question.casefold()
        if folded in requested:
            continue
        requested.add(folded)

        retrieve_node(state, retriever, sub_question, top_k)
        verdict = critique_node(state)
        if verdict.sufficient:
            if (
                verdict.requested_tool == SearchNotesTool.name
                and notes_tool is not None
                and not state.budget_spent
            ):
                search_notes_node(state, notes_tool)
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

    finish_node(state, sufficient=sufficient)
    return state
