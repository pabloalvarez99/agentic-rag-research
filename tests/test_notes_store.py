"""The note store: what a run writes down, and what every note has to carry."""

from __future__ import annotations

import pytest

from agentic_rag.agent.state import ResearchState, ResearchStatus, RunAlreadyFinished
from agentic_rag.notes import (
    MAX_CLAIM_CHARS,
    Note,
    claim_from_text,
    note_from_passage,
    note_id,
)
from agentic_rag.tools import Passage

CLAIM = "Hybrid retrieval fuses a lexical ranking with a dense one."


def passage(
    chunk_id: str = "hybrid-1",
    text: str = CLAIM,
    rank: int = 1,
    heading_path: str | None = "Hybrid retrieval > Fusion",
) -> Passage:
    return Passage(
        chunk_id=chunk_id,
        source_path="docs/hybrid.md",
        text=text,
        rank=rank,
        title="Hybrid retrieval",
        heading_path=heading_path,
    )


# --- the value type ---------------------------------------------------------


def test_a_note_carries_what_an_auditor_asks_for() -> None:
    note = note_from_passage(passage(), position=1)

    assert note is not None
    assert note.id == "note-1"
    assert note.claim == CLAIM
    assert note.source == "docs/hybrid.md"
    assert note.context == "Hybrid retrieval > Fusion"
    assert note.citation == "hybrid-1"
    assert note.is_grounded


def test_a_note_is_scored_on_its_claim_and_the_headings_it_sits_under() -> None:
    """A corpus states its subject in headings and drops it from the prose beneath."""
    note = note_from_passage(
        passage(text="A marker resolving to nothing is dropped.", heading_path="Citations"),
        position=1,
    )

    assert note is not None
    assert "citations" in note.terms
    assert "citations" not in note.claim.lower()


def test_a_passage_with_no_headings_falls_back_to_its_title_then_to_nothing() -> None:
    titled = note_from_passage(passage(heading_path=None), position=1)
    bare = note_from_passage(
        Passage(chunk_id="x-1", source_path="docs/x.md", text=CLAIM, rank=1), position=1
    )

    assert titled is not None and titled.context == "Hybrid retrieval"
    assert bare is not None and bare.context is None


def test_a_note_cannot_be_edited_after_it_is_written() -> None:
    note = Note(id="note-1", claim=CLAIM, source="docs/hybrid.md", citation="hybrid-1")

    with pytest.raises(ValueError):
        note.claim = "something the corpus never said"


def test_a_note_without_a_citation_is_not_grounded() -> None:
    note = Note(id="note-1", claim=CLAIM, source="docs/hybrid.md")

    assert note.citation is None
    assert not note.is_grounded


def test_note_ids_are_positional_and_start_at_one() -> None:
    assert note_id(1) == "note-1"
    assert note_id(12) == "note-12"
    with pytest.raises(ValueError):
        note_id(0)


# --- lifting the claim ------------------------------------------------------


def test_a_claim_is_the_chunk_verbatim_with_whitespace_collapsed() -> None:
    text = "  Hybrid retrieval fuses two rankings.\n\n  It then reranks the union.  "

    assert claim_from_text(text) == (
        "Hybrid retrieval fuses two rankings. It then reranks the union."
    )


def test_a_claim_keeps_every_sentence_the_chunk_carries() -> None:
    """The last sentence is often the one the answer rests on; nothing selects for it."""
    note = note_from_passage(
        passage(text="Context first. The measurable claim comes last."), position=1
    )

    assert note is not None
    assert "The measurable claim comes last." in note.claim


def test_an_over_long_chunk_is_cut_on_a_word_boundary() -> None:
    claim = claim_from_text("word " * (MAX_CLAIM_CHARS // 2))

    assert len(claim) <= MAX_CLAIM_CHARS + 1
    assert claim.endswith("…")
    assert "wor…" not in claim


def test_a_passage_with_no_words_supports_no_note() -> None:
    assert claim_from_text("   \n  ") == ""
    assert note_from_passage(passage(text="   \n  "), position=1) is None


# --- the store on the state -------------------------------------------------


def test_writing_a_note_mints_its_id_and_traces_it() -> None:
    state = ResearchState(question="hybrid retrieval")

    first = state.record_note(claim=CLAIM, source="docs/hybrid.md", citation="hybrid-1")
    second = state.record_note(claim="Reranking reorders.", source="docs/rerank.md")

    assert first is not None and second is not None
    assert state.note_ids == ("note-1", "note-2")
    assert state.grounded_notes == (first,)
    assert state.cited_chunk_ids == frozenset({"hybrid-1"})
    assert [event.event for event in state.trace] == ["note_added", "note_added"]
    assert state.trace[0].payload == {
        "id": "note-1",
        "claim": CLAIM,
        "source": "docs/hybrid.md",
        "context": None,
        "citation": "hybrid-1",
        "grounded": True,
    }
    assert state.trace[1].payload["grounded"] is False


def test_the_same_claim_from_the_same_chunk_is_written_once() -> None:
    state = ResearchState(question="hybrid retrieval")
    state.record_note_from_passage(passage())

    assert state.record_note_from_passage(passage()) is None
    assert len(state.notes) == 1
    assert [event.event for event in state.trace].count("note_added") == 1


def test_the_same_claim_from_a_different_chunk_is_a_separate_note() -> None:
    """Two chunks saying the same thing is corroboration, and both stay citable."""
    state = ResearchState(question="hybrid retrieval")
    state.record_note_from_passage(passage(chunk_id="hybrid-1"))
    state.record_note_from_passage(passage(chunk_id="rerank-4"))

    assert state.note_ids == ("note-1", "note-2")
    assert state.cited_chunk_ids == frozenset({"hybrid-1", "rerank-4"})


def test_an_empty_claim_is_never_stored() -> None:
    state = ResearchState(question="hybrid retrieval")

    assert state.record_note(claim="", source="docs/hybrid.md", citation="hybrid-1") is None
    assert state.notes == []
    assert state.trace == []


def test_a_finished_run_writes_no_further_notes() -> None:
    state = ResearchState(question="hybrid retrieval")
    state.finish(ResearchStatus.REFUSED, "no_evidence")

    with pytest.raises(RunAlreadyFinished):
        state.record_note(claim=CLAIM, source="docs/hybrid.md", citation="hybrid-1")


def test_the_store_is_deterministic_for_the_same_passages() -> None:
    def build() -> ResearchState:
        state = ResearchState(question="hybrid retrieval")
        for index, chunk_id in enumerate(("hybrid-1", "rerank-4"), start=1):
            state.record_note_from_passage(passage(chunk_id=chunk_id, rank=index))
        return state

    assert build().model_dump_json() == build().model_dump_json()
