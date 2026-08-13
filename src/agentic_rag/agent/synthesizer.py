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

import re
from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.agent.critic import Gap
from agentic_rag.agent.failures import ToolFailure
from agentic_rag.tools.retrieve import Passage

SNIPPET_CHARS: Final = 240
"""Longest finding printed for one passage before it is cut at a word boundary."""

_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
"""C0 and C1 control characters, none of which a report has a use for.

Retrieved text is untrusted (master plan §13.6) and a report is printed to a
terminal by the CLI. A passage carrying ``\\x1b[2J`` would clear an operator's
screen, and one carrying ``\\x08`` would delete the words in front of it — the
finding would read as something nobody retrieved. They are replaced by a space
rather than deleted, so stripping one cannot silently join two words into a
third.
"""

_MARKER_SHAPED: Final = re.compile(r"\[(\d+)\]")
"""A citation marker, as it would look if a passage or a question contained one.

The report is the one place ``[n]`` means something, and it means *this run
retrieved that*. A document that quotes a citation of its own would otherwise
print a marker resolving to nothing, which is precisely what the corpus in this
repository says a grounded system must not do.
"""


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


def _quotable(text: str) -> str:
    """Return ``text`` in the form it may be quoted inside a report.

    Two substitutions, both about text nobody in this process wrote: control
    characters become a space, and a marker shape becomes the same number in
    parentheses. The second is not cosmetic — ``[7]`` inside a passage is
    indistinguishable from a citation marker once it is printed, and a report
    whose markers do not all resolve is the failure the citation policy exists to
    prevent. The digits are kept, so nothing the source said is lost.
    """
    return _MARKER_SHAPED.sub(r"(\1)", _CONTROL.sub(" ", text))


def _snippet(text: str) -> str:
    """Return the first sentence of ``text``, cut at a word boundary if long."""
    collapsed = " ".join(_quotable(text).split())
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
    failure: ToolFailure | None = None,
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
        failure: The tool failure that ended the run. Present, it takes
            precedence over ``partial`` and ``refused``: the run stopped for a
            reason that is not about the evidence, and the report says which. A
            run with evidence prints what it grounded before the failure; a run
            without prints that no answer is available at all.

    Returns:
        The report and its citations. Citations are empty exactly when the
        evidence was.
    """
    lines: list[str] = [f"Question: {_quotable(question)}", ""]
    finding_lines, citations = _findings(evidence)

    if failure is not None and not finding_lines:
        lines.append(
            f"Unavailable: the run stopped because {failure.detail}, "
            "and it had retrieved nothing to ground an answer on."
        )
    elif refused and not finding_lines:
        lines.append("Refused: nothing was retrieved that could support an answer.")
    elif refused:
        lines.append(
            "Refused: the retrieved evidence is too thin to support an answer. "
            "What was retrieved, unaltered:"
        )
        lines.extend(["", *finding_lines])
    else:
        if failure is not None:
            lines.append(
                f"Status: degraded. The run stopped because {failure.detail}; "
                "the findings below are what it grounded first."
            )
            lines.append("")
        elif partial:
            lines.append(
                "Status: partial. The step budget ended before the evidence was sufficient; "
                "the findings below are what the run grounded."
            )
            lines.append("")
        lines.append("Findings, each one a retrieved passage:")
        lines.extend(["", *finding_lines])

    if gaps:
        lines.extend(["", "Not established by the retrieved evidence:", ""])
        lines.extend(f"- {_quotable(gap.detail)}" for gap in gaps)

    return Synthesis(report="\n".join(lines), citations=tuple(citations))
