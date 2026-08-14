"""Deciding whether the notes gathered so far support an answer.

The critic is the only component that can end the loop on success, so it is
written to be readable rather than clever: a score anyone can recompute by hand
from the state, and a threshold stated as a constant.

``score = question terms covered by grounded claims + number of grounded, on-topic notes``

It scores the run's :class:`~agentic_rag.notes.Note` store, not its raw
passage buffer, and that distinction is the point of the rule:

* **A note only counts when it is grounded.** ``citation is None`` means no
  retrieved chunk backs the claim, so it contributes to neither half. Presence of
  a citation is checked, never assumed.
* **A note only counts when it is on topic.** A grounded claim sharing no term
  with the question is evidence of something, but not of *this*. Counting notes
  by length alone is exactly the failure this rule exists to avoid: five
  retrieved passages about the wrong thing would clear any threshold.
* **Coverage alone is not enough either.** One claim that happens to repeat the
  question's vocabulary would clear a coverage-only rule while resting on a
  single source.

Neither half is a quality measure and this module does not pretend otherwise —
it is a stop rule, and its job is to be a *predictable* stop rule. The
threshold's honest justification is that it ends runs at a defensible point on
the free path; it is not tuned against a labelled set, because no labelled set
exists yet (``docs/architecture.md``).

When the evidence is not sufficient the critic names what is missing. A gap that
only says "not enough" tells the loop nothing it can act on, so every gap carries
a sentence a reader can check and, where a retrieval could still close it, a
follow-up sub-question. The critic never fills a gap by inventing a passage.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.notes import Note
from agentic_rag.text import keyword_terms

SUFFICIENT_SCORE: Final = 3
"""Score at or above which the evidence is treated as enough to answer from."""

GapKind = Literal[
    "no_evidence",
    "unanswered_sub_question",
    "uncovered_terms",
    "thin_evidence",
    "ungrounded_notes",
]
"""What kind of hole in the evidence a gap describes."""

CriticToolRequest = Literal["search_notes"]
"""Optional local tool the critic asks the loop to run before synthesis."""


class Gap(BaseModel):
    """One named hole in the evidence.

    ``detail`` is the sentence that goes into a refusal or a partial report, so
    it names the specific thing that is missing. ``follow_up`` is present only
    when another retrieval could plausibly close the gap; ``None`` means the
    loop would be spending a step to receive what it already has.
    """

    model_config = ConfigDict(frozen=True)

    kind: GapKind = Field(description="Which kind of hole this is.")
    detail: str = Field(min_length=1, description="What is missing, in a checkable sentence.")
    follow_up: str | None = Field(
        default=None,
        description="Sub-question that could close the gap, when one exists.",
    )


class Critique(BaseModel):
    """The verdict on one round of evidence, with the arithmetic behind it.

    The three inputs to the score are kept alongside the verdict rather than
    recomputed by whoever reads the trace: a stop decision nobody can reproduce
    from the record is a stop decision nobody can dispute.
    """

    model_config = ConfigDict(frozen=True)

    note_count: int = Field(ge=0, description="Notes in the store, grounded or not.")
    grounded_note_count: int = Field(
        default=0,
        ge=0,
        description="Notes whose claim carries the chunk id it was lifted from.",
    )
    relevant_note_count: int = Field(
        default=0,
        ge=0,
        description="Grounded notes whose claim shares at least one term with the question.",
    )
    keyword_overlap: int = Field(
        ge=0,
        description="Question terms appearing in at least one grounded claim.",
    )
    score: int = Field(ge=0, description="keyword_overlap + relevant_note_count.")
    sufficient: bool = Field(description="Whether the loop may stop and answer.")
    gaps: tuple[Gap, ...] = Field(
        default=(),
        description="Named holes in the evidence. Always empty when sufficient.",
    )
    requested_tool: CriticToolRequest | None = Field(
        default=None,
        description=(
            "Local post-processing tool requested before synthesis. It may only inspect "
            "evidence already gathered and does not replace a retrieval step."
        ),
    )


def _covered_terms(question: str, notes: Sequence[Note]) -> tuple[set[str], set[str]]:
    """Return the question terms covered by grounded claims, and those that are not."""
    wanted = keyword_terms(question)
    if not wanted:
        return set(), set()
    seen: set[str] = set()
    for note in notes:
        if note.is_grounded:
            seen |= note.terms
    return wanted & seen, wanted - seen


def critique(
    question: str,
    notes: Sequence[Note],
    *,
    unanswered: Sequence[str] = (),
) -> Critique:
    """Judge the notes gathered for ``question`` and name what is missing.

    Args:
        question: The research question, scored against the note store.
        notes: The run's notes, in the order they were added.
        unanswered: Sub-questions already retrieved for that returned nothing.
            They are reported as gaps but never re-issued as follow-ups: an
            identical request returns an identical empty result.

    Returns:
        The verdict, its arithmetic, and the gaps when it is not sufficient.
    """
    wanted = keyword_terms(question)
    covered, missing = _covered_terms(question, notes)
    note_count = len(notes)
    grounded = [note for note in notes if note.is_grounded]
    relevant = [note for note in grounded if not wanted or note.terms & wanted]
    score = len(covered) + len(relevant)
    sufficient = score >= SUFFICIENT_SCORE and len(relevant) >= 1
    if sufficient:
        return Critique(
            note_count=note_count,
            grounded_note_count=len(grounded),
            relevant_note_count=len(relevant),
            keyword_overlap=len(covered),
            score=score,
            sufficient=True,
            requested_tool="search_notes" if len(relevant) > 1 else None,
        )

    gaps: list[Gap] = []
    if note_count == 0 and not unanswered:
        # Before the first step there is no sub-question to name, so the gap
        # names the question. Afterwards the per-sub-question gaps below say the
        # same thing more precisely, and repeating it pads the refusal.
        gaps.append(
            Gap(
                kind="no_evidence",
                detail=f"nothing has been retrieved for {question!r}",
                follow_up=question,
            )
        )
    for sub_question in unanswered:
        gaps.append(
            Gap(
                kind="unanswered_sub_question",
                detail=f"no passage was retrieved for the sub-question {sub_question!r}",
            )
        )
    if missing:
        listed = ", ".join(sorted(missing))
        gaps.append(
            Gap(
                kind="uncovered_terms",
                detail=f"no grounded claim mentions: {listed}",
                follow_up=" ".join(sorted(missing)),
            )
        )
    if note_count and len(grounded) < note_count:
        gaps.append(
            Gap(
                kind="ungrounded_notes",
                detail=(
                    f"{note_count - len(grounded)} of {note_count} note(s) carry no chunk id "
                    "and were not scored"
                ),
            )
        )
    if note_count and not missing:
        gaps.append(
            Gap(
                kind="thin_evidence",
                detail=(
                    f"score {score} is below the threshold of {SUFFICIENT_SCORE}: "
                    f"{len(relevant)} grounded claim(s) cover the question's terms but too "
                    "thinly to answer from"
                ),
            )
        )

    return Critique(
        note_count=note_count,
        grounded_note_count=len(grounded),
        relevant_note_count=len(relevant),
        keyword_overlap=len(covered),
        score=score,
        sufficient=False,
        gaps=tuple(gaps),
    )
