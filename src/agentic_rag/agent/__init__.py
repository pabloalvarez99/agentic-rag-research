"""The agent loop and the state it carries.

M1 ships the state only. The plan / retrieve / critique loop that drives it
arrives with M2 and M3 (``docs/architecture.md``).
"""

from __future__ import annotations

from agentic_rag.agent.state import (
    DEFAULT_MAX_STEPS,
    ResearchState,
    StepBudgetExceeded,
    StepRecord,
)

__all__ = [
    "DEFAULT_MAX_STEPS",
    "ResearchState",
    "StepBudgetExceeded",
    "StepRecord",
]
