"""Deterministic search over passages already gathered by the research loop.

This is intentionally not another retriever. It cannot contact a provider or add evidence;
it lets the critic ask the loop to re-rank its own notes before synthesis. Matching is
lexical, stable, and inspectable, so the trace proves which note ids were considered useful
without making a quality claim.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.text import keyword_terms
from agentic_rag.tools.retrieve import Passage

DEFAULT_NOTES_LIMIT: Final = 5


class SearchNotesRequest(BaseModel):
    """Question and gathered notes to search locally."""

    model_config = ConfigDict(frozen=True)

    question: str = Field(min_length=1)
    notes: tuple[Passage, ...] = Field(min_length=1)
    limit: int = Field(default=DEFAULT_NOTES_LIMIT, ge=1, le=20)


class SearchNotesResult(BaseModel):
    """Original passages whose text overlaps the question, in stable score order."""

    model_config = ConfigDict(frozen=True)

    matches: tuple[Passage, ...] = ()
    inspected: int = Field(ge=0)


class SearchNotesTool:
    """Rank already-gathered evidence by deterministic lexical overlap."""

    name: Final = "search_notes"
    description: Final = (
        "Search only the notes already gathered in this run; never retrieves, generates, "
        "or contacts a provider."
    )

    def run(self, request: SearchNotesRequest) -> SearchNotesResult:
        """Return matching original passages without rewriting their content."""
        wanted = keyword_terms(request.question)
        scored: list[tuple[int, int, Passage]] = []
        for index, note in enumerate(request.notes):
            note_terms = keyword_terms(
                " ".join((note.title or "", note.heading_path or "", note.text))
            )
            overlap = len(wanted & note_terms)
            if overlap:
                scored.append((-overlap, index, note))
        scored.sort(key=lambda item: (item[0], item[1]))
        return SearchNotesResult(
            matches=tuple(item[2] for item in scored[: request.limit]),
            inspected=len(request.notes),
        )
