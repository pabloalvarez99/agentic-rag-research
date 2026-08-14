"""The second tool searches only notes already present in one run."""

from __future__ import annotations

from agentic_rag.tools import Passage, SearchNotesRequest, SearchNotesTool, Tool


def note(chunk_id: str, text: str) -> Passage:
    return Passage(chunk_id=chunk_id, source_path="docs/notes.md", text=text, rank=1)


def test_search_notes_is_a_typed_tool() -> None:
    tool = SearchNotesTool()

    assert isinstance(tool, Tool)
    assert tool.name == "search_notes"
    assert "never retrieves" in tool.description


def test_search_notes_ranks_original_notes_by_overlap_stably() -> None:
    first = note("first", "Budgets make loops stop.")
    strongest = note("strongest", "Explicit budgets and stop reasons bound agent loops.")
    unrelated = note("unrelated", "Chunking splits documents.")

    result = SearchNotesTool().run(
        SearchNotesRequest(
            question="Why do agent loops need budgets and stop reasons?",
            notes=(first, strongest, unrelated),
        )
    )

    assert result.inspected == 3
    assert [match.chunk_id for match in result.matches] == ["strongest", "first"]
    assert result.matches[0] is strongest


def test_search_notes_is_deterministic_and_never_adds_content() -> None:
    notes = (note("a", "Research traces explain stop reasons."),)
    request = SearchNotesRequest(question="research stop reasons", notes=notes)

    first = SearchNotesTool().run(request)
    second = SearchNotesTool().run(request)

    assert first == second
    assert first.matches == notes
