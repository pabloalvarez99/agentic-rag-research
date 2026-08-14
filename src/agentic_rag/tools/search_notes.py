"""Deterministic search over the notes a run has already written.

This is intentionally not another retriever. It cannot contact a provider and it cannot
add a note; it lets the critic ask the loop to re-rank its own store before synthesis.
Matching is lexical, stable, and inspectable, so the trace proves which note ids were
considered useful without making a quality claim.

It reads the note store rather than the passage buffer because a note is what the run
is relying on: the claim, its source, and the chunk id that backs it. Ranking passages
would rank text the run never committed to.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.notes import Note
from agentic_rag.text import keyword_terms

DEFAULT_NOTES_LIMIT: Final = 5


class SearchNotesRequest(BaseModel):
    """Question and the notes to search locally."""

    model_config = ConfigDict(frozen=True)

    question: str = Field(min_length=1)
    notes: tuple[Note, ...] = Field(min_length=1)
    limit: int = Field(default=DEFAULT_NOTES_LIMIT, ge=1, le=20)


class SearchNotesResult(BaseModel):
    """The original notes whose claims overlap the question, in stable score order."""

    model_config = ConfigDict(frozen=True)

    matches: tuple[Note, ...] = ()
    inspected: int = Field(ge=0)


class SearchNotesTool:
    """Rank the run's own notes by deterministic lexical overlap."""

    name: Final = "search_notes"
    description: Final = (
        "Search only the notes already written in this run; never retrieves, generates, "
        "or contacts a provider."
    )

    def run(self, request: SearchNotesRequest) -> SearchNotesResult:
        """Return matching notes without rewriting any claim.

        Ties are broken by insertion order, so two runs over the same store produce the
        same ranking and the same trace.

        Args:
            request: The question and the notes to rank.

        Returns:
            The matching notes, best first, and how many were inspected.
        """
        wanted = keyword_terms(request.question)
        scored: list[tuple[int, int, Note]] = []
        for index, note in enumerate(request.notes):
            overlap = len(wanted & note.terms)
            if overlap:
                scored.append((-overlap, index, note))
        scored.sort(key=lambda item: (item[0], item[1]))
        return SearchNotesResult(
            matches=tuple(item[2] for item in scored[: request.limit]),
            inspected=len(request.notes),
        )
