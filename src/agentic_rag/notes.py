"""The note store: what a run believes, and what each belief rests on.

Before this module a run's memory was a list of retrieved passages. That is a
buffer, not a store: it answers "what came back?" and nothing else. Three
questions an auditor actually asks — *which claim is the run relying on?*,
*where did it come from?*, *can I follow it?* — were answerable only by reading
the passage text and reconstructing the mapping by hand.

A :class:`Note` answers all three in one typed record:

* ``claim`` is what the run is relying on, **lifted verbatim** from the passage.
  Nothing here rewrites, summarises or generates. A note whose claim was
  paraphrased would be a claim nobody retrieved, and its citation would point at
  a passage that does not say it.

  It is the whole retrieved chunk, whitespace-collapsed, and not a sentence
  selected from it. Picking one sentence would be a summarisation decision, and
  the free path has nothing that can make it: a first-sentence heuristic drops
  the sentence the answer actually rests on whenever a chunk leads with context,
  and it does so invisibly — the citation still resolves, so nothing looks wrong.
  Chunks arrive from a heading-structured corpus and are already the smallest
  unit with provenance (``agentic_rag.corpus``), so the chunk *is* the claim
  until a component exists that can honestly narrow it.
* ``source`` is the corpus-relative path the claim came from. Like
  :class:`~agentic_rag.tools.passage.Passage.source_path` it is carried and never
  resolved, opened, or joined against a local directory — it arrives from a
  retrieval service and is an identifier a human uses, not a file to read.
* ``citation`` is the chunk id the claim was lifted from, or ``None`` for a note
  no retrieved passage backs. ``None`` is not a hypothetical: it is what makes
  "grounded" a property the critic can *count* rather than assume, and the free
  path deliberately produces only grounded notes so the ungrounded case stays a
  measured zero rather than an untested branch.

Ids are positional (``note-1``, ``note-2``) and assigned by the store in add
order. They are stable for a given question and budget on the free path, which
is what lets a trace be compared byte for byte between two runs.

The module sits at the package root, beside :mod:`agentic_rag.text`, and imports
nothing at runtime. Both the agent (which writes notes) and the tools (which rank
them) depend on this shape, so a note that lived inside either package would make
the two import each other.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.text import keyword_terms

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance, not behaviour
    from agentic_rag.tools.passage import Passage

NOTE_ID_PREFIX: Final = "note"
"""Prefix of every note id. The suffix is the note's 1-based position."""

MAX_CLAIM_CHARS: Final = 2_000
"""Longest claim kept before it is cut at a word boundary.

A bound on what one note may carry, not an editorial judgement: every chunk the
committed corpus produces is far shorter, so on the free path nothing is ever
cut. It exists because a hostile or misconfigured retrieval service can return a
chunk of any size, and a note store is memory a run carries for its whole life.
"""

_TRAILING_WORD: Final = re.compile(r"\s+\S*$")
"""Matches the last whitespace-separated fragment, used to cut on a word boundary."""


def note_id(position: int) -> str:
    """Return the id of the note in 1-based ``position``.

    Args:
        position: Where the note sits in the store, counting from one.

    Returns:
        The positional id, e.g. ``note-3``.

    Raises:
        ValueError: ``position`` is not at least one, which would produce an id
            that no note in a store can ever have.
    """
    if position < 1:
        raise ValueError("note positions are 1-based")
    return f"{NOTE_ID_PREFIX}-{position}"


def claim_from_text(text: str) -> str:
    """Return ``text`` as a claim: verbatim, whitespace-collapsed, length-bounded.

    Collapsing runs of whitespace is the only edit made, and it is made so two
    backends that differ in line wrapping produce the same note for the same
    chunk. Every word survives it, so the claim is still a string a reader finds
    in the cited chunk.

    A chunk longer than :data:`MAX_CLAIM_CHARS` is cut at a word boundary and
    marked with an ellipsis. The cut is a bound on the store, not a judgement
    about content — the citation still points at the whole chunk, and on the free
    path no chunk comes close to the bound.

    Args:
        text: Passage text exactly as a backend returned it.

    Returns:
        The claim, or an empty string when ``text`` carries no words.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= MAX_CLAIM_CHARS:
        return collapsed
    head = _TRAILING_WORD.sub("", collapsed[: MAX_CLAIM_CHARS + 1])
    return f"{head or collapsed[:MAX_CLAIM_CHARS]}…"


class Note(BaseModel):
    """One claim the run is relying on, and what backs it.

    Frozen for the same reason a passage is: a note that can be edited after the
    fact is a note whose citation cannot be checked against anything.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, description="Positional id, stable within one run.")
    claim: str = Field(min_length=1, description="The sentence relied on, lifted verbatim.")
    source: str = Field(description="Corpus-relative path the claim came from. Never resolved.")
    citation: str | None = Field(
        default=None,
        description="Chunk id the claim was lifted from. None when no passage backs it.",
    )

    @property
    def is_grounded(self) -> bool:
        """Return whether a retrieved chunk backs this claim."""
        return self.citation is not None

    @property
    def terms(self) -> set[str]:
        """Return the scoring terms of the claim, tokenised like everything else."""
        return keyword_terms(self.claim)


def note_from_passage(passage: Passage, *, position: int) -> Note | None:
    """Return the note a passage supports, or ``None`` when it supports none.

    A passage whose text carries no words yields no note. Storing an empty claim
    would inflate every count the critic reads while adding nothing a reader
    could check.

    Args:
        passage: The retrieved chunk.
        position: 1-based position the note will occupy in the store.

    Returns:
        The note, or ``None`` for a passage with no claim in it.
    """
    claim = claim_from_text(passage.text)
    if not claim:
        return None
    return Note(
        id=note_id(position),
        claim=claim,
        source=passage.source_path,
        citation=passage.chunk_id,
    )


__all__ = [
    "MAX_CLAIM_CHARS",
    "NOTE_ID_PREFIX",
    "Note",
    "claim_from_text",
    "note_from_passage",
    "note_id",
]
