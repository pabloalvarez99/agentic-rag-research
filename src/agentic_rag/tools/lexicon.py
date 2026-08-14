"""Fixture lexicon / term lookup — the third free-path tool.

Looks up a term against the committed fake corpus only. No network, no model,
no synonym API. Returns short definitions lifted from matching document text so
the loop can spend a budgeted call without pretending to research the live web.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.corpus import Document
from agentic_rag.text import keyword_terms
from agentic_rag.tools.retrieve import DEFAULT_CORPUS

DEFAULT_LEXICON_LIMIT: Final = 3


class LexiconRequest(BaseModel):
    """One term (or short phrase) to resolve against the fixture corpus."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    term: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=DEFAULT_LEXICON_LIMIT, ge=1, le=10)


class LexiconEntry(BaseModel):
    """One definitional hit from the fixture."""

    model_config = ConfigDict(frozen=True)

    term: str
    definition: str
    chunk_id: str
    source_path: str


class LexiconResult(BaseModel):
    """Ordered lexicon hits for one term."""

    model_config = ConfigDict(frozen=True)

    term: str
    entries: tuple[LexiconEntry, ...] = ()
    backend: str = "fixture"


class LexiconTool:
    """Deterministic term lookup over the packaged corpus documents."""

    name: Final = "lexicon"
    description: Final = (
        "Look up a term in the committed fixture corpus and return short definitional "
        "passages; never contacts the network or a synonym service."
    )

    def __init__(self, corpus: Sequence[Document] | None = None) -> None:
        """Bind an optional corpus; default is the package fixture."""
        self._corpus: tuple[Document, ...] = tuple(corpus) if corpus is not None else DEFAULT_CORPUS

    def run(self, request: LexiconRequest) -> LexiconResult:
        """Return the best-matching fixture documents for ``request.term``."""
        wanted = keyword_terms(request.term)
        if not wanted:
            wanted = {request.term.casefold()}
        term_cf = request.term.casefold()
        scored: list[tuple[int, int, Document]] = []
        for index, document in enumerate(self._corpus):
            hay = " ".join(
                part
                for part in (
                    document.title or "",
                    document.heading_path or "",
                    document.text,
                )
            ).casefold()
            terms = keyword_terms(hay)
            overlap = len(wanted & terms)
            if term_cf in hay:
                overlap += 2
            if overlap:
                scored.append((-overlap, index, document))
        scored.sort(key=lambda item: (item[0], item[1]))
        entries = tuple(
            LexiconEntry(
                term=request.term,
                definition=_first_sentence(document.text),
                chunk_id=document.chunk_id,
                source_path=document.source_path,
            )
            for _, _, document in scored[: request.limit]
        )
        return LexiconResult(term=request.term, entries=entries)


def _first_sentence(text: str, limit: int = 240) -> str:
    """Return a short definitional slice of passage text."""
    cleaned = " ".join(text.split())
    if ". " in cleaned:
        cleaned = cleaned.split(". ", 1)[0].strip()
        if cleaned and not cleaned.endswith("."):
            cleaned += "."
    if len(cleaned) > limit:
        return cleaned[: limit - 1].rstrip() + "…"
    return cleaned


__all__ = [
    "DEFAULT_LEXICON_LIMIT",
    "LexiconEntry",
    "LexiconRequest",
    "LexiconResult",
    "LexiconTool",
]
