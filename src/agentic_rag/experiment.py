"""Experiment records for the free-path research lab.

A finished run is already a full artifact (status, notes, trace). An experiment
record is the compact, lab-facing summary: seed, budgets, note ids, stop reason,
and optional pack hash. Compare and pack UI still use full payloads; this model
is the ledger line for scorecards and experiment packs (docs/SEASON.md).
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Final, Mapping, Self

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.agent.state import ResearchState, StopReason

DEFAULT_SEED: Final = 0
"""Free-path planner/critic are deterministic; seed 0 is the documented default."""

TOOL_RETRIEVE: Final = "retrieve"
TOOL_SEARCH_NOTES: Final = "search_notes"
TOOL_LEXICON: Final = "lexicon"


class ToolBudget(BaseModel):
    """Per-run global step budget plus optional per-tool call caps."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_steps: int = Field(ge=1, le=20)
    max_calls: dict[str, int] = Field(default_factory=dict)


class ExperimentRecord(BaseModel):
    """One lab experiment: the durable summary of a finished research run.

    Fields match SEASON Month 1: ``id``, ``seed``, ``budget``, note ids,
    ``stop_reason``, ``pack_hash``. Status and tool-call counts are included so a
    scorecard can read the record without re-opening the full artifact.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, description="Stable experiment or request id.")
    seed: int = Field(default=DEFAULT_SEED, ge=0)
    question: str = Field(min_length=1)
    budget: ToolBudget
    note_ids: tuple[str, ...] = ()
    status: str = Field(min_length=1)
    stop_reason: StopReason
    tool_calls: dict[str, int] = Field(default_factory=dict)
    pack_hash: str | None = Field(
        default=None,
        description="SHA-256 of the experiment pack when this run is pack-bound.",
    )
    retriever: str = Field(default="fake")
    trace_event_count: int = Field(default=0, ge=0)

    @classmethod
    def from_state(
        cls,
        state: ResearchState,
        *,
        experiment_id: str,
        seed: int = DEFAULT_SEED,
        retriever: str = "fake",
        pack_hash: str | None = None,
        max_calls: Mapping[str, int] | None = None,
    ) -> Self:
        """Build a record from a finished :class:`ResearchState`."""
        if not state.is_finished or state.stop_reason is None:
            raise ValueError("only a finished run with a stop reason becomes an experiment")
        calls = _tool_calls_from_trace(state.trace)
        if max_calls is not None:
            budget_calls = dict(max_calls)
        else:
            budget_calls = dict(getattr(state, "max_tool_calls", {}) or {})
        if TOOL_RETRIEVE not in budget_calls:
            budget_calls[TOOL_RETRIEVE] = state.max_steps
        return cls(
            id=experiment_id,
            seed=seed,
            question=state.question,
            budget=ToolBudget(max_steps=state.max_steps, max_calls=budget_calls),
            note_ids=tuple(state.note_ids),
            status=state.status.value,
            stop_reason=state.stop_reason,
            tool_calls=calls,
            pack_hash=pack_hash,
            retriever=retriever,
            trace_event_count=len(state.trace),
        )

    @classmethod
    def from_run_artifact(
        cls,
        artifact: Any,
        *,
        seed: int = DEFAULT_SEED,
        pack_hash: str | None = None,
        max_calls: Mapping[str, int] | None = None,
    ) -> Self:
        """Build a record from a stored or downloaded run artifact.

        ``artifact`` is duck-typed (``RunArtifact``) to avoid an import cycle
        with :mod:`agentic_rag.api.runs`.
        """
        calls = _tool_calls_from_trace(artifact.trace)
        budget_calls = dict(max_calls) if max_calls is not None else {}
        if TOOL_RETRIEVE not in budget_calls:
            budget_calls[TOOL_RETRIEVE] = artifact.max_steps
        status = artifact.status.value if hasattr(artifact.status, "value") else str(artifact.status)
        return cls(
            id=artifact.request_id,
            seed=seed,
            question=artifact.question,
            budget=ToolBudget(max_steps=artifact.max_steps, max_calls=budget_calls),
            note_ids=tuple(note.id for note in artifact.notes),
            status=status,
            stop_reason=artifact.stop_reason,
            tool_calls=calls,
            pack_hash=pack_hash,
            retriever=artifact.retriever,
            trace_event_count=len(artifact.trace),
        )


def _tool_calls_from_trace(trace: Any) -> dict[str, int]:
    """Count tool_call events by tool name."""
    counts: dict[str, int] = {}
    for event in trace:
        name = getattr(event, "event", None)
        payload = getattr(event, "payload", None)
        if name != "tool_call" or not isinstance(payload, dict):
            continue
        tool = payload.get("tool")
        if isinstance(tool, str) and tool:
            counts[tool] = counts.get(tool, 0) + 1
    return counts


def pack_bytes_hash(payload: bytes) -> str:
    """Return a stable hex SHA-256 for pack bytes."""
    return sha256(payload).hexdigest()


__all__ = [
    "DEFAULT_SEED",
    "TOOL_LEXICON",
    "TOOL_RETRIEVE",
    "TOOL_SEARCH_NOTES",
    "ExperimentRecord",
    "ToolBudget",
    "pack_bytes_hash",
]
