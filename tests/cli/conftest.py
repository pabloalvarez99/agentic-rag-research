"""Stubs for the CLI tests.

Deliberately local rather than imported from ``tests/api``. ``tests/`` is not a package,
so a cross-package import would mean making it one — a repository-wide change to how
every test module is collected, in exchange for forty lines. The doubles below are the
smallest set the CLI cases need, and a test double that drifts from its sibling is a
test that fails loudly rather than one that lies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentic_rag.agent.state import (
    DEFAULT_MAX_STEPS,
    ResearchState,
    ResearchStatus,
    StopReason,
    TraceListener,
)
from agentic_rag.agent.synthesizer import synthesize
from agentic_rag.api.schemas import RetrieverChoice
from agentic_rag.tools.retrieve import (
    DEFAULT_TOP_K,
    FakeRetrievalBackend,
    RetrieveRequest,
    RetrieveTool,
)

ANSWERABLE = "What does hybrid retrieval buy over dense retrieval alone?"
OFF_CORPUS = "What were the quarterly revenues in Patagonia?"

STOP_REASONS: dict[ResearchStatus, StopReason] = {
    ResearchStatus.DONE: "evidence_sufficient",
    ResearchStatus.REFUSED: "no_evidence",
    ResearchStatus.BUDGET_EXHAUSTED: "budget_spent",
    ResearchStatus.DEGRADED: "evidence_sufficient",
}


def build_state(
    *,
    status: ResearchStatus = ResearchStatus.DONE,
    question: str = ANSWERABLE,
) -> ResearchState:
    """Return a finished state carrying ``status``, built through the public recorders."""
    state = ResearchState(question=question, max_steps=1)
    state.record_plan([question])
    tool = RetrieveTool(FakeRetrievalBackend())
    request = RetrieveRequest(question=question)
    state.record_tool_call(tool.name, request)
    state.record_retrieval(request, tool.run(request))
    state.record_synthesis(synthesize(question, state.evidence))
    state.finish(status, STOP_REASONS[status])
    return state


@dataclass
class StubRunner:
    """A runner that returns a prepared state or raises a prepared error."""

    state: ResearchState | None = None
    error: Exception | None = None

    def __call__(
        self,
        question: str,
        *,
        tool: RetrieveTool | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        top_k: int = DEFAULT_TOP_K,
        max_tool_calls: object | None = None,
        listener: TraceListener | None = None,
    ) -> ResearchState:
        del max_tool_calls  # accepted for ResearchService parity; stubs ignore caps
        if self.error is not None:
            raise self.error
        state = self.state if self.state is not None else build_state(question=question)
        if listener is not None:
            for event in state.trace:
                listener(event)
        return state


@dataclass
class RecordingFactory:
    """A retriever factory that always yields the in-process fixture, and remembers asks."""

    choices: list[RetrieverChoice] = field(default_factory=list)

    def __call__(self, choice: RetrieverChoice) -> RetrieveTool:
        self.choices.append(choice)
        return RetrieveTool(FakeRetrievalBackend())
