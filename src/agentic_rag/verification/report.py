"""What a verification returns: a closed set of codes and the evidence for each.

A verifier that returns a boolean tells you a run is wrong and nothing else, and
one that raises tells you about the first thing it found. This one returns every
violation it can see, each with a stable code a test or a dashboard can count,
the sentence a person needs, and — where the problem is a specific event — the
index of that event in the trace.

Codes are a closed set for the same reason stop reasons are: something downstream
will branch on them, and a code invented at a call site is a code nobody can
enumerate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ViolationCode = Literal[
    "unknown_event",
    "event_out_of_order",
    "plan_missing",
    "tool_call_unresolved",
    "tool_outcome_unpaired",
    "stop_missing",
    "stop_repeated",
    "stop_not_last",
    "status_not_terminal",
    "status_reason_mismatch",
    "budget_exceeded",
    "synthesis_missing",
    "report_missing",
    "citation_marker_unresolved",
    "citation_unprinted",
    "citation_out_of_order",
    "citation_not_grounded",
    "evidence_duplicated",
    "trace_state_mismatch",
]
"""Every way a run can contradict the contract in `docs/workstreams/a4-core-reliability.md`."""


class Violation(BaseModel):
    """One way a run contradicts the contract.

    Frozen, like everything else a verification produces: a report whose findings
    can be edited afterwards is a report nobody can quote.
    """

    model_config = ConfigDict(frozen=True)

    code: ViolationCode = Field(description="Stable slug for the invariant that does not hold.")
    detail: str = Field(min_length=1, description="What is wrong, in a checkable sentence.")
    event_index: int | None = Field(
        default=None,
        ge=0,
        description="Position in the trace this points at, when it points at one event.",
    )


class VerificationReport(BaseModel):
    """Everything one verification found, in the order the checks ran.

    Empty is the good outcome, and it is spelled :attr:`ok` so a test reads as a
    claim about the run rather than as a claim about a list.
    """

    model_config = ConfigDict(frozen=True)

    violations: tuple[Violation, ...] = Field(
        default=(),
        description="Every violation found. Empty when the run holds the contract.",
    )

    @property
    def ok(self) -> bool:
        """Return whether the run holds every invariant."""
        return not self.violations

    @property
    def codes(self) -> tuple[ViolationCode, ...]:
        """Return the code of each violation, in order and with repeats."""
        return tuple(violation.code for violation in self.violations)

    def summary(self) -> str:
        """Return one line per violation, for a message a person will read."""
        if self.ok:
            return "no violations"
        return "\n".join(
            f"{violation.code}: {violation.detail}" for violation in self.violations
        )
