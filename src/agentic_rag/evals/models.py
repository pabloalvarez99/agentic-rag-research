"""Typed inputs and outputs for the free-path evaluation harness."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

TerminalStatus = Literal["done", "refused", "budget_exhausted"]
StopReason = Literal[
    "evidence_sufficient",
    "no_evidence",
    "insufficient_evidence",
    "budget_spent",
    "tool_budget_spent",
]


class GoldenExpectation(BaseModel):
    """Mechanical constraints for one completed research run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: TerminalStatus
    stop_reason: StopReason
    steps_used: int = Field(ge=0)
    min_citations: int = Field(ge=0)
    max_citations: int = Field(ge=0)
    cite_chunk_ids_any: tuple[str, ...] = ()
    min_distinct_sources: int = Field(ge=0)
    gap_kinds_any: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        """Reject internally contradictory citation bounds."""
        if self.min_citations > self.max_citations:
            raise ValueError("min_citations cannot exceed max_citations")
        if self.stop_reason == "no_evidence" and self.max_citations != 0:
            raise ValueError("no_evidence expectations cannot allow citations")
        return self


class GoldenCase(BaseModel):
    """One deterministic question and its expected terminal behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    question: str = Field(min_length=1)
    max_steps: int = Field(ge=1, le=20)
    top_k: int = Field(ge=1, le=50)
    pair_id: str | None
    max_tool_calls: dict[str, int] | None = None
    expect: GoldenExpectation
    why: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_budget(self) -> Self:
        """Ensure citation expectations fit inside the configured retrieval budget."""
        if self.expect.max_citations > self.max_steps * self.top_k:
            raise ValueError("max_citations exceeds max_steps * top_k")
        return self


class CaseResult(BaseModel):
    """Observed metrics and expectation verdict for one golden case."""

    model_config = ConfigDict(frozen=True)

    id: str
    category: str
    status: str
    stop_reason: str
    steps_used: int = Field(ge=0)
    has_citations: bool
    citation_count: int = Field(ge=0)
    passed: bool
    failures: tuple[str, ...] = ()


class EvalMetrics(BaseModel):
    """Aggregate free-path *control* metrics across the golden dataset.

    These numbers measure terminal behavior, budgets, and citation presence on a
    committed fixture. They do not measure answer quality, retrieval quality, or
    uplift over a single pass — and they never claim to beat another system.
    """

    model_config = ConfigDict(frozen=True)

    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    mean_steps_used: float = Field(ge=0.0, description="Mean retrieval steps spent per case.")
    has_citations_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="Fraction of cases whose report carried at least one citation.",
    )
    citation_present_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="Alias of has_citations_rate for scorecard readers expecting this name.",
    )
    status_counts: dict[str, int] = Field(description="Terminal status distribution.")
    stop_reason_counts: dict[str, int] = Field(
        description="Stop-reason distribution from the closed set the loop emits.",
    )
    refused_unanswerable: int = Field(
        ge=0,
        description="Unanswerable-category cases that ended refused.",
    )
    unanswerable_cases: int = Field(
        ge=0,
        description="Cases labelled category=unanswerable in the golden set.",
    )
    refused_unanswerable_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="refused_unanswerable / unanswerable_cases (1.0 when the slice is empty).",
    )


class EvalReport(BaseModel):
    """Reproducible scorecard emitted by ``python -m agentic_rag.evals.run``."""

    model_config = ConfigDict(frozen=True)

    provider: Literal["fake"] = "fake"
    billed_usd: float = Field(default=0.0, ge=0.0)
    dataset: str
    metrics: EvalMetrics
    results: tuple[CaseResult, ...]

    @property
    def all_passed(self) -> bool:
        """Return whether every golden expectation held."""
        return (
            self.metrics.total_cases > 0
            and self.metrics.passed_cases == self.metrics.total_cases
        )
