"""Deliberately broken implementations of the research loop.

These exist to answer the question a green scorecard cannot answer on its own:
would this harness notice? Each runner below breaks exactly one property that the
invariants claim to enforce, and the tests assert the matching invariant fires.

A harness that reports everything clean over a correct implementation and *also*
reports everything clean over these is measuring nothing. That is the failure mode
these are here to make visible, and it is why ``evaluate_case`` takes the runner
as a parameter at all.
"""

from __future__ import annotations

from agentic_rag.agent.state import ResearchState, ResearchStatus
from agentic_rag.agent.synthesizer import Citation, Synthesis
from agentic_rag.tools.retrieve import RetrieveRequest, RetrieveTool


def _retrieve(state: ResearchState, tool: RetrieveTool, question: str, top_k: int) -> None:
    """Spend one honest step, tracing it the way the loop does."""
    request = RetrieveRequest(question=question, top_k=top_k)
    state.record_tool_call(RetrieveTool.name, request)
    state.record_retrieval(request, tool.run(request))


def always_refuses(
    question: str, tool: RetrieveTool, max_steps: int, top_k: int
) -> ResearchState:
    """Never retrieves anything and refuses every question.

    Breaks nothing structural on the refusal path, which is the point: a loop can
    be trivially "safe" by never answering, and only the expectation metrics
    notice. It is the control for reward hacking through refusal.
    """
    state = ResearchState(question=question, max_steps=max_steps)
    state.record_plan([question])
    state.record_synthesis(Synthesis(report="Refused: nothing was retrieved.", citations=()))
    state.finish(ResearchStatus.REFUSED, "no_evidence")
    return state


def fabricates_citations(
    question: str, tool: RetrieveTool, max_steps: int, top_k: int
) -> ResearchState:
    """Retrieves honestly, then cites a passage that does not exist."""
    state = ResearchState(question=question, max_steps=max_steps)
    state.record_plan([question])
    _retrieve(state, tool, question, top_k)
    state.record_synthesis(
        Synthesis(
            report="- a passage nobody retrieved [1]",
            citations=(
                Citation(
                    marker=1,
                    source_path="docs/invented.md",
                    chunk_id="invented-1",
                    snippet="a passage nobody retrieved",
                ),
            ),
        )
    )
    state.finish(ResearchStatus.DONE, "evidence_sufficient")
    return state


def prints_an_unresolvable_marker(
    question: str, tool: RetrieveTool, max_steps: int, top_k: int
) -> ResearchState:
    """Prints a marker with no citation behind it."""
    state = ResearchState(question=question, max_steps=max_steps)
    state.record_plan([question])
    _retrieve(state, tool, question, top_k)
    passages = list(state.evidence)
    citations = (
        (
            Citation(
                marker=1,
                source_path=passages[0].source_path,
                chunk_id=passages[0].chunk_id,
                snippet=passages[0].text[:80],
            ),
        )
        if passages
        else ()
    )
    state.record_synthesis(
        Synthesis(report="- grounded [1]\n- invented [9]", citations=citations)
    )
    state.finish(ResearchStatus.DONE, "evidence_sufficient")
    return state


def overruns_the_budget(
    question: str, tool: RetrieveTool, max_steps: int, top_k: int
) -> ResearchState:
    """Spends more steps than the case allowed, by giving itself a larger budget."""
    state = ResearchState(question=question, max_steps=20)
    state.record_plan([question])
    for _ in range(min(20, max_steps + 2)):
        _retrieve(state, tool, question, top_k)
    state.record_synthesis(Synthesis(report="Status: partial.", citations=()))
    state.finish(ResearchStatus.DONE, "evidence_sufficient")
    return state


def answers_without_citing(
    question: str, tool: RetrieveTool, max_steps: int, top_k: int
) -> ResearchState:
    """Produces a confident report and cites nothing at all."""
    state = ResearchState(question=question, max_steps=max_steps)
    state.record_plan([question])
    _retrieve(state, tool, question, top_k)
    state.record_synthesis(Synthesis(report="The answer is yes.", citations=()))
    state.finish(ResearchStatus.DONE, "evidence_sufficient")
    return state


def skips_the_plan(question: str, tool: RetrieveTool, max_steps: int, top_k: int) -> ResearchState:
    """Retrieves before recording any plan."""
    state = ResearchState(question=question, max_steps=max_steps)
    _retrieve(state, tool, question, top_k)
    state.record_plan([question])
    state.record_synthesis(Synthesis(report="Status: partial.", citations=()))
    state.finish(ResearchStatus.DONE, "evidence_sufficient")
    return state


BROKEN_RUNNERS = {
    "always_refuses": always_refuses,
    "fabricates_citations": fabricates_citations,
    "prints_an_unresolvable_marker": prints_an_unresolvable_marker,
    "overruns_the_budget": overruns_the_budget,
    "answers_without_citing": answers_without_citing,
    "skips_the_plan": skips_the_plan,
}
"""Every broken runner, by name, so a test can sweep them all."""
