"""Checking a finished run against the contract it claims to satisfy.

The agent produces a state and a trace; this package answers whether they are a
run the loop could have produced. It is separate from
:mod:`agentic_rag.agent` on purpose — a component that certifies itself
certifies its own bugs along with it, and the point of the trace is that someone
who does not trust the agent can audit it.

    >>> from agentic_rag.agent import run_research
    >>> from agentic_rag.verification import verify_run
    >>> verify_run(run_research("What does hybrid retrieval buy?")).ok
    True

Nothing here writes. The invariants it enforces are tabulated in
``docs/workstreams/a4-core-reliability.md``.
"""

from __future__ import annotations

from agentic_rag.verification.report import VerificationReport, Violation, ViolationCode
from agentic_rag.verification.rules import (
    MARKER,
    TRACE_EVENT_NAMES,
    stop_reasons_for,
    verify_run,
)

__all__ = [
    "MARKER",
    "TRACE_EVENT_NAMES",
    "VerificationReport",
    "Violation",
    "ViolationCode",
    "stop_reasons_for",
    "verify_run",
]
