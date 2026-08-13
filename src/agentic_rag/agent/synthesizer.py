"""Writing the run's report, from retrieved passages and nothing else.

The rule this module exists to enforce: **every sentence in a report that makes a
claim about the world is a passage that was retrieved, and carries the marker
that points at it.** There is no model here, free or otherwise. A synthesiser
that paraphrases would be the one place in the loop where an unsupported
sentence could enter a report while every other component behaved correctly, so
at this milestone it does not paraphrase at all: it selects, orders, and marks.

Three kinds of line appear in a report, and only the first makes a claim:

* a **finding**, which is passage text and carries ``[n]``;
* a **status line**, which describes the run itself and is checkable against the
  trace;
* a **gap**, which states what the evidence did *not* establish.

That is what makes a partial report publishable: a run whose budget ended early
can print the findings it did ground, provided it also prints what it never
closed. A report that stops mentioning its gaps when it runs out of steps is how
a thin run comes to read like a complete one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.agent.critic import Gap
from agentic_rag.tools.retrieve import Passage

SNIPPET_CHARS: Final = 240
"""Longest finding printed for one passage before it is cut at a word boundary."""


class Citation(BaseModel):
    """One marker in a report, resolved to the passage it points at.

    The shape is the portfolio-wide citation object: ``start_line`` and
    ``end_line`` stay ``None`` here because a prose corpus has no line spans to
    report, and a field filled with a plausible-looking number is worse than one
    left empty. The code-intelligence project in the series fills them.
    """

    model_config = ConfigDict(frozen=True)

    marker: int = Field(ge=1, description="The number printed as [n] in the report.")
    source_path: str = Field(description="Corpus-relative path of the cited document.")
    chunk_id: str | None = Field(default=None, description="Stable id of the cited chunk.")
    snippet: str | None = Field(default=None, description="The cited text as it was printed.")
    start_line: int | None = Field(default=None, description="Unused for prose corpora.")
    end_line: int | None = Field(default=None, description="Unused for prose corpora.")


class Synthesis(BaseModel):
    """A report and the citations its markers resolve to.

    The two are produced together, from the same ordered evidence, so a marker
    that resolves to nothing cannot be created in the first place.
    """

    model_config = ConfigDict(frozen=True)

    report: str = Field(min_length=1, description="The text shown to whoever asked.")
    citations: tuple[Citation, ...] = Field(
        default=(),
        description="One entry per marker, in marker order.",
    )


def _snippet(text: str) -> str:
    """Return the first sentence of ``text``, cut at a word boundary if long."""
    collapsed = " ".join(text.split())
    head, separator, _ = collapsed.partition(". ")
    sentence = f"{head}." if separator else collapsed
    if len(sentence) <= SNIPPET_CHARS:
        return sentence
    cut = sentence[:SNIPPET_CHARS].rsplit(" ", 1)[0]
    return f"{cut}..."


def _findings(evidence: Sequence[Passage]) -> tuple[list[str], list[Citation]]:
    """Return the marked finding lines and the citations they resolve to."""
    lines: list[str] = []
    citations: list[Citation] = []
    for marker, passage in enumerate(evidence, start=1):
        snippet = _snippet(passage.text)
        lines.append(f"- {snippet} [{marker}]")
        citations.append(
            Citation(
                marker=marker,
                source_path=passage.source_path,
                chunk_id=passage.chunk_id,
                snippet=snippet,
            )
        )
    return lines, citations


def synthesize(
    question: str,
    evidence: Sequence[Passage],
    *,
    gaps: Sequence[Gap] = (),
    partial: bool = False,
    refused: bool = False,
) -> Synthesis:
    """Compose the report for a finished run.

    Args:
        question: The research question, restated as a heading. A restatement is
            not a claim, so it needs no marker.
        evidence: Distinct passages in the order they were first retrieved. The
            markers follow that order, so ``[1]`` is always the first thing the
            run found.
        gaps: What the critic named as missing. Printed whenever present, which
            is what keeps a partial report honest.
        partial: The run stopped before its evidence was sufficient but is still
            printing what it grounded.
        refused: The run is declining to answer. Any evidence it did gather is
            still printed and still cited — a refusal that hides its passages is
            harder to check than one that shows them.

    Returns:
        The report and its citations. Citations are empty exactly when the
        evidence was.
    """
    lines: list[str] = [f"Question: {question}", ""]
    finding_lines, citations = _findings(evidence)

    if refused and not finding_lines:
        lines.append("Refused: nothing was retrieved that could support an answer.")
    elif refused:
        lines.append(
            "Refused: the retrieved evidence is too thin to support an answer. "
            "What was retrieved, unaltered:"
        )
        lines.extend(["", *finding_lines])
    else:
        if partial:
            lines.append(
                "Status: partial. The step budget ended before the evidence was sufficient; "
                "the findings below are what the run grounded."
            )
            lines.append("")
        lines.append("Findings, each one a retrieved passage:")
        lines.extend(["", *finding_lines])

    if gaps:
        lines.extend(["", "Not established by the retrieved evidence:", ""])
        lines.extend(f"- {gap.detail}" for gap in gaps)

    return Synthesis(report="\n".join(lines), citations=tuple(citations))
