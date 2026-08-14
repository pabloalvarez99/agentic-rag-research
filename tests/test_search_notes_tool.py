"""The second tool searches only the notes one run has already written."""

from __future__ import annotations

from agentic_rag.notes import Note, note_from_passage
from agentic_rag.tools import Passage, SearchNotesRequest, SearchNotesTool, Tool


def note(chunk_id: str, text: str, position: int = 1) -> Note:
    passage = Passage(chunk_id=chunk_id, source_path="docs/notes.md", text=text, rank=1)
    written = note_from_passage(passage, position=position)
    assert written is not None
    return written


def test_search_notes_is_a_typed_tool() -> None:
    tool = SearchNotesTool()

    assert isinstance(tool, Tool)
    assert tool.name == "search_notes"
    assert "never retrieves" in tool.description


def test_search_notes_ranks_the_run_s_own_notes_by_overlap_stably() -> None:
    first = note("first", "Budgets make loops stop.", position=1)
    strongest = note("strongest", "Explicit budgets and stop reasons bound agent loops.", 2)
    unrelated = note("unrelated", "Chunking splits documents.", position=3)

    result = SearchNotesTool().run(
        SearchNotesRequest(
            question="Why do agent loops need budgets and stop reasons?",
            notes=(first, strongest, unrelated),
        )
    )

    assert result.inspected == 3
    assert [match.id for match in result.matches] == ["note-2", "note-1"]
    assert [match.citation for match in result.matches] == ["strongest", "first"]
    assert result.matches[0] is strongest


def test_search_notes_is_deterministic_and_never_adds_content() -> None:
    notes = (note("a", "Research traces explain stop reasons."),)
    request = SearchNotesRequest(question="research stop reasons", notes=notes)

    first = SearchNotesTool().run(request)
    second = SearchNotesTool().run(request)

    assert first == second
    assert first.matches == notes


def test_search_notes_ranks_an_ungrounded_note_on_its_claim_alone() -> None:
    """It ranks what the run wrote down; grounding is the critic's question, not its."""
    floating = Note(id="note-1", claim="Stop reasons bound a loop.", source="docs/notes.md")

    result = SearchNotesTool().run(
        SearchNotesRequest(question="stop reasons", notes=(floating,))
    )

    assert result.matches == (floating,)
    assert result.matches[0].citation is None
