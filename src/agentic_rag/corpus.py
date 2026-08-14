"""The committed markdown corpus the free path retrieves over.

The corpus lives as markdown files rather than as literals inside a module for
two reasons. Editing the evidence a demo returns should not be editing Python,
so a reader can add a document without touching the retrieval code. And the
loader is the same shape as the ingest step of a real system — walk sources,
split on heading structure, emit chunks with provenance — so what the free path
demonstrates is the pipeline, not a hand-written result set.

The files ship *inside* the package (``agentic_rag/data/fake_corpus``) rather
than at the repository root. A corpus reachable only from a git checkout would
make ``pip install agentic-rag-research`` produce an agent whose default
retriever finds nothing, and the free path has to survive being installed.

Nothing here is a retrieval technique. Splitting on ``##`` is the smallest rule
that gives every passage a heading path to cite, which is the property the rest
of the system depends on.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

CORPUS_PACKAGE: Final = "agentic_rag.data.fake_corpus"
"""Import path of the shipped corpus directory."""

CORPUS_LABEL: Final = "fake_corpus"
"""Directory name reported in ``source_path``, so a citation names its corpus."""

_TITLE: Final = re.compile(r"^#\s+(?P<title>\S.*)$")
_SECTION: Final = re.compile(r"^##\s+(?P<heading>\S.*)$")
_DEEPER: Final = re.compile(r"^#{3,}\s")


class CorpusError(ValueError):
    """A corpus file could not be read as a sequence of citable passages.

    Raised at load time rather than at search time on purpose: a malformed
    document that is merely skipped becomes a retrieval result that is quietly
    missing evidence, and nothing downstream can tell that apart from a corpus
    that never covered the question.
    """


class Document(BaseModel):
    """One passage of the local corpus, before a query gives it a rank.

    Rank is a property of a search, not of a document, so it is absent here and
    assigned by the backend that searches over these.
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=1)
    source_path: str
    text: str
    title: str | None = None
    heading_path: str | None = None


def _paragraphs(lines: list[str]) -> str:
    """Join a section's body lines into text, preserving paragraph breaks."""
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    return "\n\n".join(blocks)


def parse_document(text: str, *, stem: str) -> list[Document]:
    """Split one markdown file into the passages it contributes to the corpus.

    A single ``#`` line names the document; every ``##`` line starts a passage.
    Deeper headings are not a second level of chunk — they are folded into the
    passage they sit in, because a chunk that is one sentence long carries less
    context than the citation pointing at it needs.

    Args:
        text: Full contents of the markdown file.
        stem: File name without its extension, used to build chunk ids.

    Returns:
        The document's passages, in file order.

    Raises:
        CorpusError: The file has no title, has no ``##`` section, opens with
            body text before its first section, or leaves a section empty.
    """
    title: str | None = None
    heading: str | None = None
    body: list[str] = []
    documents: list[Document] = []

    def close() -> None:
        if heading is None:
            return
        passage = _paragraphs(body)
        if not passage:
            raise CorpusError(f"{stem}.md: section {heading!r} has no text")
        documents.append(
            Document(
                chunk_id=f"{stem}-{len(documents) + 1}",
                source_path=f"{CORPUS_LABEL}/{stem}.md",
                text=passage,
                title=title,
                heading_path=f"{title} > {heading}",
            )
        )

    for line in text.splitlines():
        if (section := _SECTION.match(line)) is not None:
            close()
            heading = section.group("heading").strip()
            body = []
            continue
        if (found := _TITLE.match(line)) is not None:
            if title is not None:
                raise CorpusError(f"{stem}.md: a document has one title, found a second")
            title = found.group("title").strip()
            continue
        if _DEEPER.match(line) is not None:
            body.append(line.lstrip("# ").strip())
            continue
        if line.strip() and heading is None:
            raise CorpusError(f"{stem}.md: text appears before the first '##' section")
        body.append(line)

    close()

    if title is None:
        raise CorpusError(f"{stem}.md: no '# ' title line")
    if not documents:
        raise CorpusError(f"{stem}.md: no '## ' sections, so it contributes no passages")
    return documents


def _markdown_files(directory: Traversable) -> Iterator[Traversable]:
    """Yield the directory's markdown files in name order.

    Sorted rather than in directory order because corpus position breaks scoring
    ties, so an unsorted walk would make ranking depend on the filesystem.
    """
    yield from sorted(
        (entry for entry in directory.iterdir() if entry.name.endswith(".md")),
        key=lambda entry: entry.name,
    )


def load_corpus(directory: Traversable | None = None) -> tuple[Document, ...]:
    """Load every passage of a corpus directory, in a deterministic order.

    Args:
        directory: Directory of markdown files. Defaults to the corpus shipped
            inside the package.

    Returns:
        Every passage of every file, files in name order and passages in file
        order.

    Raises:
        CorpusError: A file is malformed, the directory holds no markdown, or
            two passages claim the same chunk id.
    """
    root = files(CORPUS_PACKAGE) if directory is None else directory
    documents: list[Document] = []
    for entry in _markdown_files(root):
        documents.extend(
            parse_document(entry.read_text(encoding="utf-8"), stem=entry.name.removesuffix(".md"))
        )

    if not documents:
        raise CorpusError("corpus directory holds no markdown passages")

    seen = {document.chunk_id for document in documents}
    if len(seen) != len(documents):
        raise CorpusError("corpus has duplicate chunk ids")
    return tuple(documents)
