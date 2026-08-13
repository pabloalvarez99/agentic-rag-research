"""The state the bounded loop carries from one step to the next.

Minimal on purpose. At M1 the loop needs three things and no more: the question
under research, somewhere to accumulate evidence without duplicating it, and a
bound on how many steps may run. The bound lives here rather than in a caller's
``for`` loop because an agent whose budget is enforced at the call site is an
agent with as many budget rules as it has call sites.

Only the ``record_*`` methods change a state, so the invariants — steps never
exceed the budget, evidence never repeats a chunk id — hold in one place.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.tools.retrieve import Passage, RetrieveRequest, RetrieveResult, RetrieveTool

DEFAULT_MAX_STEPS = 4
"""Steps one research run may take before it must answer or refuse."""


class StepBudgetExceeded(RuntimeError):
    """A step was recorded after the budget was spent.

    An exception rather than a silently dropped step: a run that quietly stops
    recording still looks complete in the trace, and the missing work is only
    visible to whoever compares step counts afterwards.
    """


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
    """Question under research, budget left, steps taken, evidence gathered.

    Evidence is deduplicated by chunk id, first occurrence kept: two sub-questions
    routinely retrieve the same passage, and counting it twice would make thin
    evidence read as corroborated.
    """

    question: str = Field(min_length=1, description="The research question as it was asked.")
    max_steps: int = Field(
        default=DEFAULT_MAX_STEPS,
        ge=1,
        le=20,
        description="Hard cap on tool calls for this run.",
    )
    steps: list[StepRecord] = Field(
        default_factory=list,
        description="Completed tool calls, oldest first.",
    )
    evidence: list[Passage] = Field(
        default_factory=list,
        description="Distinct passages gathered so far, in the order they were first seen.",
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

    def record_retrieval(self, request: RetrieveRequest, result: RetrieveResult) -> StepRecord:
        """Spend one step on a completed retrieval and absorb its evidence.

        Args:
            request: The sub-question that was retrieved for.
            result: What the retrieve tool returned, including an empty result.

        Returns:
            The record appended to :attr:`steps`.

        Raises:
            StepBudgetExceeded: The budget was already spent.
        """
        if self.budget_spent:
            raise StepBudgetExceeded(
                f"budget of {self.max_steps} step(s) is spent; the run must answer or refuse"
            )

        known = set(self.evidence_ids)
        for passage in result.passages:
            if passage.chunk_id not in known:
                self.evidence.append(passage)
                known.add(passage.chunk_id)

        record = StepRecord(
            tool=RetrieveTool.name,
            request=request.question,
            evidence_ids=tuple(passage.chunk_id for passage in result.passages),
        )
        self.steps.append(record)
        return record
