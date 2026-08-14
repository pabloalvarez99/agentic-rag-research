"""Stubs shared by the runtime-surface tests.

Two things live here and nothing else: a way to build a finished ``ResearchState`` with
any terminal status, and a runner that records what it was called with. Together they
let a test drive the transport through outcomes the free-path loop cannot produce on
demand — a backend failure, the declared-but-unproduced ``degraded`` status — without a
socket, an environment variable, or a credential.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from agentic_rag.agent.state import (
    DEFAULT_MAX_STEPS,
    ResearchState,
    ResearchStatus,
    StopReason,
    TraceListener,
)
from agentic_rag.agent.synthesizer import synthesize
from agentic_rag.api.schemas import RetrieverChoice
from agentic_rag.api.service import ResearchService
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
    steps: int = 1,
) -> ResearchState:
    """Return a finished state carrying ``status``, built through the public recorders.

    Going through ``record_*`` rather than assigning fields means the fixture obeys the
    same invariants a real run does, so a test that passes against it is not passing
    against a shape the loop can never produce.
    """
    state = ResearchState(question=question, max_steps=max(steps, 1))
    state.record_plan([question])
    tool = RetrieveTool(FakeRetrievalBackend())
    for _ in range(steps):
        request = RetrieveRequest(question=question)
        state.record_tool_call(tool.name, request)
        state.record_retrieval(request, tool.run(request))
    state.record_synthesis(synthesize(question, state.evidence))
    state.finish(status, STOP_REASONS[status])
    return state


@dataclass
class RecordedRun:
    """One call a stub runner received."""

    question: str
    max_steps: int
    top_k: int
    tool: RetrieveTool | None


@dataclass
class StubRunner:
    """A runner that records its calls and returns or raises whatever a test wants."""

    state: ResearchState | None = None
    error: Exception | None = None
    calls: list[RecordedRun] = field(default_factory=list)

    def __call__(
        self,
        question: str,
        *,
        tool: RetrieveTool | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        top_k: int = DEFAULT_TOP_K,
        listener: TraceListener | None = None,
    ) -> ResearchState:
        self.calls.append(
            RecordedRun(question=question, max_steps=max_steps, top_k=top_k, tool=tool)
        )
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


@pytest.fixture
def offline_service() -> ResearchService:
    """The real loop, pinned to the in-process backend so no test can reach a network."""
    return ResearchService(retriever_factory=RecordingFactory())
