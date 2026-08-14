"""The state the bounded loop carries from one step to the next.

One object holds everything a run is and everything it did: the question, the
plan, the evidence, the budget, the verdicts, the report, and the trace. Two
rules keep it from becoming a bag of fields:

* **Only the ``record_*`` methods change a state.** The invariants — steps never
  exceed the budget, evidence never repeats a chunk id, a terminal status is set
  once — hold in one place instead of at every call site that writes a field.
* **Nothing is stored twice.** A step records the chunk ids it returned, not the
  passage text; the trace records what happened, not a second copy of the state.
  Two places able to disagree about what a run saw is worse than one place that
  is merely incomplete.

Every mutation also appends its trace event, so a run cannot advance without
leaving a record. The trace carries no timestamps: a run over the free path is
deterministic, and two runs of the same question produce byte-identical traces —
which is what lets a test assert on one. Wall-clock timings belong to the
observability layer that arrives with the HTTP route.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.agent.critic import Critique, Gap
from agentic_rag.agent.synthesizer import Citation, Synthesis
from agentic_rag.tools.retrieve import Passage, RetrieveRequest, RetrieveResult, RetrieveTool
from agentic_rag.tools.search_notes import SearchNotesRequest, SearchNotesResult, SearchNotesTool

DEFAULT_MAX_STEPS = 4
"""Retrieval steps one research run may take before it must answer or refuse."""


class ResearchStatus(StrEnum):
    """Where a run is, and if it is over, how it ended.

    ``DEGRADED`` is declared but not yet produced: it is reserved for a run that
    completed with a tool failure it worked around, and no tool on the free path
    can fail that way. Naming it here rather than adding it later keeps the
    status set stable for anything that already switches on it.
    """

    RUNNING = "running"
    DONE = "done"
    REFUSED = "refused"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEGRADED = "degraded"

    @property
    def is_terminal(self) -> bool:
        """Return whether this status means the loop has stopped."""
        return self is not ResearchStatus.RUNNING


TERMINAL_STATUSES: Final = frozenset(
    status for status in ResearchStatus if status is not ResearchStatus.RUNNING
)
"""The statuses a finished run may carry."""

StopReason = Literal["evidence_sufficient", "no_evidence", "insufficient_evidence", "budget_spent"]
"""Why the loop stopped, from a closed set so a caller can branch on it."""

TraceEventName = Literal[
    "plan_created",
    "tool_call",
    "tool_result",
    "critique",
    "synthesize",
    "stop",
]
"""The events a run may record, in the order a complete run emits them."""


class StepBudgetExceeded(RuntimeError):
    """A step was recorded after the budget was spent.

    An exception rather than a silently dropped step: a run that quietly stops
    recording still looks complete in the trace, and the missing work is only
    visible to whoever compares step counts afterwards.
    """


class RunAlreadyFinished(RuntimeError):
    """A finished run was asked to record more work.

    A second terminal status would overwrite the first, and the trace would show
    a run that stopped twice for different reasons.
    """


class TraceEvent(BaseModel):
    """One thing that happened, in the order it happened.

    ``payload`` is a plain mapping rather than a per-event model because the
    trace is read as JSON by people and by tests, and a union of six models buys
    nothing at the point where it is serialised. What each event carries is
    documented on the ``record_*`` method that emits it.
    """

    model_config = ConfigDict(frozen=True)

    event: TraceEventName = Field(description="What happened.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Details of the event.")


class StepRecord(BaseModel):
    """One completed tool call, in the order it happened.

    It carries chunk ids and not passage text. The text is in
    :attr:`ResearchState.evidence` exactly once, and a step that copied it would
    make two places able to disagree about what a step actually saw.
    """

    model_config = ConfigDict(frozen=True)

    tool: str = Field(description="Name of the tool that ran.")
    request: str = Field(description="Sub-question the step was given.")
    evidence_ids: tuple[str, ...] = Field(
        default=(),
        description="Chunk ids the step returned, including ones already known.",
    )

    @property
    def found_evidence(self) -> bool:
        """Return whether the step returned any evidence at all."""
        return bool(self.evidence_ids)


class ResearchState(BaseModel):
    """Question, plan, budget, evidence, verdicts, report and trace of one run.

    Evidence is deduplicated by chunk id, first occurrence kept: two sub-questions
    routinely retrieve the same passage, and counting it twice would make thin
    evidence read as corroborated. That order is also the citation order, so
    ``[1]`` is always the first thing the run found.
    """

    question: str = Field(min_length=1, description="The research question as it was asked.")
    max_steps: int = Field(
        default=DEFAULT_MAX_STEPS,
        ge=1,
        le=20,
        description="Hard cap on retrieval calls for this run.",
    )
    plan: list[str] = Field(
        default_factory=list,
        description="Sub-questions the planner produced, in order.",
    )
    steps: list[StepRecord] = Field(
        default_factory=list,
        description="Completed tool calls, oldest first.",
    )
    evidence: list[Passage] = Field(
        default_factory=list,
        description="Distinct passages gathered so far, in the order they were first seen.",
    )
    gaps: list[Gap] = Field(
        default_factory=list,
        description="What the most recent critique found missing. Empty once sufficient.",
    )
    status: ResearchStatus = Field(
        default=ResearchStatus.RUNNING,
        description="Where the run is, and if it is over, how it ended.",
    )
    stop_reason: StopReason | None = Field(
        default=None,
        description="Why the loop stopped. Set with the terminal status.",
    )
    report: str | None = Field(
        default=None,
        description="The composed report. None until the run finishes.",
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="One entry per marker in the report, in marker order.",
    )
    trace: list[TraceEvent] = Field(
        default_factory=list,
        description="Every recorded event, oldest first.",
    )

    @property
    def steps_taken(self) -> int:
        """Return how many tool calls have been recorded."""
        return len(self.steps)

    @property
    def budget_remaining(self) -> int:
        """Return how many tool calls are still allowed."""
        return max(self.max_steps - self.steps_taken, 0)

    @property
    def budget_spent(self) -> bool:
        """Return whether the run must now answer or refuse."""
        return self.budget_remaining == 0

    @property
    def has_evidence(self) -> bool:
        """Return whether anything has been retrieved yet."""
        return bool(self.evidence)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        """Return the chunk ids gathered so far, in first-seen order."""
        return tuple(passage.chunk_id for passage in self.evidence)

    @property
    def is_finished(self) -> bool:
        """Return whether a terminal status has been recorded."""
        return self.status.is_terminal

    @property
    def requested_sub_questions(self) -> tuple[str, ...]:
        """Return every sub-question already retrieved for, oldest first."""
        return tuple(step.request for step in self.steps if step.tool == RetrieveTool.name)

    @property
    def unanswered_sub_questions(self) -> tuple[str, ...]:
        """Return the sub-questions that were retrieved for and returned nothing."""
        return tuple(
            step.request
            for step in self.steps
            if step.tool == RetrieveTool.name and not step.found_evidence
        )

    def _record(self, event: TraceEventName, payload: dict[str, Any]) -> TraceEvent:
        """Append one trace event and return it."""
        entry = TraceEvent(event=event, payload=payload)
        self.trace.append(entry)
        return entry

    def _require_running(self) -> None:
        """Raise if the run has already recorded a terminal status."""
        if self.is_finished:
            raise RunAlreadyFinished(
                f"run finished with status {self.status.value!r}; it records no further work"
            )

    def record_plan(self, sub_questions: Sequence[str]) -> None:
        """Adopt the plan for this run.

        Traces ``plan_created`` with ``sub_questions``.

        Args:
            sub_questions: Ordered sub-questions, at least one.

        Raises:
            RunAlreadyFinished: The run has already stopped.
            ValueError: The plan is empty, which would leave the loop nothing to
                do while still looking like a planned run.
        """
        self._require_running()
        if not sub_questions:
            raise ValueError("a plan needs at least one sub-question")
        self.plan = list(sub_questions)
        self._record("plan_created", {"sub_questions": list(self.plan)})

    def record_tool_call(self, tool: str, request: RetrieveRequest) -> None:
        """Note that a tool is about to run.

        Traces ``tool_call`` with ``tool``, ``question`` and ``top_k``. It is
        recorded before the call so a run that dies inside a tool still shows
        what it was doing.

        Args:
            tool: Name of the tool being called.
            request: The request it is being called with.

        Raises:
            RunAlreadyFinished: The run has already stopped.
        """
        self._require_running()
        self._record(
            "tool_call",
            {"tool": tool, "question": request.question, "top_k": request.top_k},
        )

    def record_retrieval(self, request: RetrieveRequest, result: RetrieveResult) -> StepRecord:
        """Spend one step on a completed retrieval and absorb its evidence.

        Traces ``tool_result`` with the backend that served the call, every
        chunk id it returned, and the subset that was new. The difference
        between the two is what makes a step that re-retrieved known passages
        distinguishable from one that found nothing.

        Args:
            request: The sub-question that was retrieved for.
            result: What the retrieve tool returned, including an empty result.

        Returns:
            The record appended to :attr:`steps`.

        Raises:
            RunAlreadyFinished: The run has already stopped.
            StepBudgetExceeded: The budget was already spent.
        """
        self._require_running()
        if self.budget_spent:
            raise StepBudgetExceeded(
                f"budget of {self.max_steps} step(s) is spent; the run must answer or refuse"
            )

        known = set(self.evidence_ids)
        new_ids: list[str] = []
        for passage in result.passages:
            if passage.chunk_id not in known:
                self.evidence.append(passage)
                known.add(passage.chunk_id)
                new_ids.append(passage.chunk_id)

        record = StepRecord(
            tool=RetrieveTool.name,
            request=request.question,
            evidence_ids=tuple(passage.chunk_id for passage in result.passages),
        )
        self.steps.append(record)
        self._record(
            "tool_result",
            {
                "tool": record.tool,
                "backend": result.backend,
                "question": record.request,
                "evidence_ids": list(record.evidence_ids),
                "new_evidence_ids": new_ids,
            },
        )
        return record

    def record_notes_search_call(self, request: SearchNotesRequest) -> None:
        """Record the critic-requested local search before it executes."""
        self._require_running()
        self._record(
            "tool_call",
            {
                "tool": SearchNotesTool.name,
                "question": request.question,
                "note_count": len(request.notes),
                "limit": request.limit,
            },
        )

    def record_notes_search(
        self,
        request: SearchNotesRequest,
        result: SearchNotesResult,
    ) -> TraceEvent:
        """Record a completed local search without changing retrieval-step accounting."""
        self._require_running()
        return self._record(
            "tool_result",
            {
                "tool": SearchNotesTool.name,
                "backend": "in_process",
                "question": request.question,
                "evidence_ids": [note.chunk_id for note in result.matches],
                "inspected": result.inspected,
            },
        )

    def record_critique(self, verdict: Critique) -> None:
        """Adopt a critique's verdict and its named gaps.

        Traces ``critique`` with the whole arithmetic, so the stop decision is
        reproducible from the trace alone.

        Args:
            verdict: What the critic concluded about the evidence so far.

        Raises:
            RunAlreadyFinished: The run has already stopped.
        """
        self._require_running()
        self.gaps = list(verdict.gaps)
        self._record(
            "critique",
            {
                "note_count": verdict.note_count,
                "keyword_overlap": verdict.keyword_overlap,
                "score": verdict.score,
                "sufficient": verdict.sufficient,
                "gaps": [gap.detail for gap in verdict.gaps],
                "requested_tool": verdict.requested_tool,
            },
        )

    def record_synthesis(self, synthesis: Synthesis) -> None:
        """Adopt the composed report and its citations.

        Traces ``synthesize`` with the markers emitted and how many passages
        were available to cite.

        Args:
            synthesis: The report and the citations its markers resolve to.

        Raises:
            RunAlreadyFinished: The run has already stopped.
        """
        self._require_running()
        self.report = synthesis.report
        self.citations = list(synthesis.citations)
        self._record(
            "synthesize",
            {
                "citation_markers": [citation.marker for citation in synthesis.citations],
                "evidence_available": len(self.evidence),
            },
        )

    def finish(self, status: ResearchStatus, reason: StopReason) -> None:
        """Record how the run ended.

        Traces ``stop``, which is the last event of every run whatever the
        outcome. A run that refused is the one most worth reading later, so the
        trace is not conditional on success.

        Args:
            status: The terminal status.
            reason: Why the loop stopped.

        Raises:
            RunAlreadyFinished: A terminal status was already recorded.
            ValueError: ``status`` is not terminal.
        """
        self._require_running()
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"{status.value!r} is not a terminal status")
        self.status = status
        self.stop_reason = reason
        self._record(
            "stop",
            {
                "status": status.value,
                "reason": reason,
                "steps_used": self.steps_taken,
                "max_steps": self.max_steps,
            },
        )
