"""The markdown corpus loader, exercised on hand-written files.

Every test here builds its own directory, so the shipped corpus can grow a
document without any of them changing. The shipped corpus is asserted on only
where the property under test is about *it* — that it exists, that it loads, and
that loading it twice is the same corpus.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_rag.corpus import (
    CORPUS_LABEL,
    CorpusError,
    Document,
    load_corpus,
    parse_document,
)

WELL_FORMED = """# Retrieval

## Hybrid search

Dense and sparse rankings are fused.

## Reranking

A cross-encoder reorders the shortlist.
"""


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


# --- parsing one file -------------------------------------------------------


def test_each_section_becomes_one_passage_in_file_order() -> None:
    documents = parse_document(WELL_FORMED, stem="retrieval")

    assert [document.chunk_id for document in documents] == ["retrieval-1", "retrieval-2"]
    assert documents[0].text == "Dense and sparse rankings are fused."
    assert documents[1].text == "A cross-encoder reorders the shortlist."


def test_a_passage_carries_the_provenance_a_citation_points_at() -> None:
    document = parse_document(WELL_FORMED, stem="retrieval")[0]

    assert document.title == "Retrieval"
    assert document.heading_path == "Retrieval > Hybrid search"
    assert document.source_path == f"{CORPUS_LABEL}/retrieval.md"


def test_paragraph_breaks_survive_and_line_wrapping_does_not() -> None:
    text = "# T\n\n## S\n\nfirst line\nsecond line\n\nnext paragraph\n"

    assert parse_document(text, stem="t")[0].text == "first line second line\n\nnext paragraph"


def test_a_deeper_heading_stays_inside_the_passage_it_sits_in() -> None:
    text = "# T\n\n## S\n\nbody\n\n### Detail\n\nmore body\n"

    documents = parse_document(text, stem="t")

    assert len(documents) == 1
    assert "Detail" in documents[0].text
    assert "more body" in documents[0].text


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("## S\n\nbody\n", "no '# ' title"),
        ("# T\n\nbody with no section\n", "before the first"),
        ("# T\n\n## S\n\n", "has no text"),
        ("# T\n\n# Second\n\n## S\n\nbody\n", "one title"),
    ],
)
def test_a_malformed_document_is_rejected_at_load_time(text: str, reason: str) -> None:
    with pytest.raises(CorpusError, match=reason):
        parse_document(text, stem="broken")


# --- loading a directory ----------------------------------------------------


def test_files_load_in_name_order_so_ranking_does_not_depend_on_the_filesystem(
    tmp_path: Path,
) -> None:
    write(tmp_path, "zulu.md", "# Z\n\n## S\n\nzulu body\n")
    write(tmp_path, "alpha.md", "# A\n\n## S\n\nalpha body\n")

    documents = load_corpus(tmp_path)

    assert [document.chunk_id for document in documents] == ["alpha-1", "zulu-1"]


def test_non_markdown_files_are_not_part_of_the_corpus(tmp_path: Path) -> None:
    write(tmp_path, "notes.txt", "not a passage")
    write(tmp_path, "doc.md", "# D\n\n## S\n\nbody\n")

    assert [document.chunk_id for document in load_corpus(tmp_path)] == ["doc-1"]


def test_a_directory_with_no_markdown_is_an_error_rather_than_an_empty_corpus(
    tmp_path: Path,
) -> None:
    write(tmp_path, "notes.txt", "not a passage")

    with pytest.raises(CorpusError, match="no markdown"):
        load_corpus(tmp_path)


def test_one_malformed_file_fails_the_load_instead_of_being_skipped(tmp_path: Path) -> None:
    write(tmp_path, "good.md", "# G\n\n## S\n\nbody\n")
    write(tmp_path, "bad.md", "no title and no section\n")

    with pytest.raises(CorpusError):
        load_corpus(tmp_path)


# --- the shipped corpus -----------------------------------------------------


def test_the_shipped_corpus_loads_from_the_installed_package() -> None:
    documents = load_corpus()

    assert len(documents) >= 5
    assert all(isinstance(document, Document) for document in documents)


def test_loading_the_shipped_corpus_twice_gives_the_same_corpus() -> None:
    assert load_corpus() == load_corpus()


def test_the_shipped_corpus_covers_the_themes_the_agent_is_demonstrated_on() -> None:
    sources = {document.source_path for document in load_corpus()}

    assert {
        f"{CORPUS_LABEL}/{name}.md"
        for name in ("hybrid-retrieval", "agent-loops", "citations", "refusal", "multi-hop")
    } <= sources
