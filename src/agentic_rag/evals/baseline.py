"""The single retrieval pass the loop wraps, measured on the same fixture.

``docs/architecture.md`` states the comparison this project exists to make: what
does a bounded agent loop add over one retrieval pass? The honest version of that
comparison at this milestone is narrow, and saying exactly how narrow is the point
of this module.

**What it is.** One call to the same `retrieve` tool, with the whole question and
the same ``top_k``, against the same in-process fixture. No plan, no critique, no
follow-up. It is the floor the loop has to beat on evidence gathered.

**What it is not.** It is not the comparison the architecture document describes,
which pairs the agent against production-rag answering directly. It produces no
answer, so it supports no statement about answer quality, faithfulness or
usefulness. Both sides retrieve by lexical overlap over five committed passages, so
a difference here is a difference in *control flow* — how many distinct passages a
question ends up grounded in — and nothing else. A reader who takes an evidence
delta on this fixture as a retrieval-quality result has been misled, so the
scorecard labels it every time it prints it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.tools import RetrieveRequest, RetrieveTool

BASELINE_LABEL = "single-pass retrieval over the same fixture; control-flow reference only"
"""Printed next to every baseline number, in the JSON and in the Markdown."""


class BaselineResult(BaseModel):
    """What one retrieval pass over the whole question returned."""

    model_config = ConfigDict(frozen=True)

    label: str = Field(default=BASELINE_LABEL, description="What this reference is.")
    evidence_ids: tuple[str, ...] = Field(description="Chunk ids the single pass returned.")
    source_paths: tuple[str, ...] = Field(description="Distinct source paths it reached.")
    backend: str = Field(description="Backend that served the pass.")

    @property
    def evidence_count(self) -> int:
        """Return how many distinct passages the single pass returned."""
        return len(set(self.evidence_ids))


def run_baseline(tool: RetrieveTool, question: str, *, top_k: int) -> BaselineResult:
    """Retrieve once for the whole question, the way a system with no loop would.

    Args:
        tool: The retrieve tool, already bound to a backend.
        question: The question, unsplit and unmodified.
        top_k: The same per-step passage cap the agent run was given.

    Returns:
        What the single pass found.
    """
    result = tool.run(RetrieveRequest(question=question, top_k=top_k))
    return BaselineResult(
        evidence_ids=tuple(passage.chunk_id for passage in result.passages),
        source_paths=tuple(sorted({passage.source_path for passage in result.passages})),
        backend=result.backend,
    )
