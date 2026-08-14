"""Diff two finished-run payloads without looking anything up by id.

Server-side ids die with the isolate that minted them. A Vercel recycle, a second
instance, or an eviction from the bounded store all make ``GET /v1/runs/{id}`` a
404 while the JSON a reviewer already downloaded is still the run. Compare
therefore takes two complete artifacts as the request body: the files are the
source of truth, and this module never touches :class:`~agentic_rag.api.runs.RunStore`.

The diff is typed and field-oriented rather than a generic JSON patch. A hiring
manager reading two runs side by side cares about stop reason, steps, notes and
citations — not that ``trace[7].payload`` shuffled. Field order is fixed so two
identical inputs produce a byte-stable empty response.
"""

from __future__ import annotations

from typing import Final, cast

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.api.runs import RunArtifact

COMPARE_PATH: Final = "/v1/runs/compare"
"""POST body is two full run payloads; no id is resolved on the server."""

# Order is the product: stop reason first, then the evidence a reviewer audits.
_COMPARED_FIELDS: Final = (
    "status",
    "stop_reason",
    "steps_used",
    "max_steps",
    "question",
    "retriever",
    "report",
    "citations",
    "notes",
    "trace",
)


class CompareRequest(BaseModel):
    """Two finished-run payloads to place next to each other.

    Either side may come from a download, a prior ``POST /v1/research`` body
    promoted to a :class:`RunArtifact`, or a hand-edited fixture. Unknown fields
    are rejected so a misspelled key cannot silently drop half the comparison.
    """

    model_config = ConfigDict(extra="forbid")

    left: RunArtifact = Field(description="First finished run, as a complete payload.")
    right: RunArtifact = Field(description="Second finished run, as a complete payload.")


class FieldDiff(BaseModel):
    """One field that differs between the two payloads."""

    model_config = ConfigDict(frozen=True)

    field: str = Field(description="Canonical field name on the run artifact.")
    left: object = Field(description="Value from the left payload.")
    right: object = Field(description="Value from the right payload.")


class CompareResponse(BaseModel):
    """Typed field-level diff of two finished runs.

    ``identical`` is true only when every compared field matches. ``diffs`` is
    empty in that case and ordered by :data:`_COMPARED_FIELDS` otherwise, so the
    response is byte-stable for a given pair of inputs.
    """

    model_config = ConfigDict(frozen=True)

    identical: bool = Field(description="True when every compared field matches.")
    diffs: tuple[FieldDiff, ...] = Field(
        default=(),
        description="Ordered field differences; empty when identical.",
    )
    left_request_id: str = Field(description="Correlation id carried by the left payload.")
    right_request_id: str = Field(description="Correlation id carried by the right payload.")


def _field_value(artifact: RunArtifact, field: str) -> object:
    """Return the JSON-ready value of one compared field."""
    value = getattr(artifact, field)
    if field in {"citations", "notes", "trace"}:
        return [item.model_dump(mode="json") for item in value]
    if hasattr(value, "value"):
        return cast(object, value.value)
    return cast(object, value)


def compare_runs(left: RunArtifact, right: RunArtifact) -> CompareResponse:
    """Return the typed field-level diff of two finished-run payloads.

    Args:
        left: First artifact.
        right: Second artifact.

    Returns:
        An empty diff when every compared field matches; otherwise one
        :class:`FieldDiff` per differing field, in stable field order.
    """
    diffs: list[FieldDiff] = []
    for field in _COMPARED_FIELDS:
        left_value = _field_value(left, field)
        right_value = _field_value(right, field)
        if left_value != right_value:
            diffs.append(FieldDiff(field=field, left=left_value, right=right_value))
    return CompareResponse(
        identical=not diffs,
        diffs=tuple(diffs),
        left_request_id=left.request_id,
        right_request_id=right.request_id,
    )


__all__ = [
    "COMPARE_PATH",
    "CompareRequest",
    "CompareResponse",
    "FieldDiff",
    "compare_runs",
]
