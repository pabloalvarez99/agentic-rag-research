"""The ``retrieve`` tool and the retrieval backends behind it.

The tool runs one sub-question against a backend and returns ranked passages
carrying the identity a citation needs. It does not plan, it does not answer, and
it does not reorder what came back: ranking belongs to the retrieval service
(``docs/architecture.md``), and a tool that quietly improves a ranking makes the
service impossible to measure.

Two backends implement the seam described in ``docs/architecture.md``, and the
tool cannot tell them apart:

* :class:`FakeRetrievalBackend` — an in-process fixture over a small committed
  corpus, deterministic per sub-question. The default, and what makes the loop
  runnable in CI and on a laptop with no credential. It is a fixture, not a
  simulation: it supports no claim about retrieval quality.
* :class:`~agentic_rag.retrievers.http_p1.HttpRetrievalBackend` — opt-in, built
  only when ``PRODUCTION_RAG_URL`` names a running production-rag instance. No
  default test reaches for it, because no default test should need a service
  started to pass. It lives in :mod:`agentic_rag.retrievers` with the pinned
  upstream contract it speaks, and is re-exported here so every existing import
  keeps working.

:class:`~agentic_rag.retrievers.passage.Passage` moved to the same package for
the same reason and is re-exported here too.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.retrievers.http_p1 import HttpRetrievalBackend
from agentic_rag.retrievers.passage import Passage
from agentic_rag.text import keyword_terms
from agentic_rag.tools.base import ToolError

PRODUCTION_RAG_URL_ENV: Final = "PRODUCTION_RAG_URL"
"""Environment variable that opts the tool into the hosted retrieval service."""

DEFAULT_TOP_K: Final = 5
"""Passages one retrieval step returns unless the caller asks for another number."""


class RetrieveRequest(BaseModel):
    """One sub-question to run against the retrieval boundary.

    Unknown fields are rejected so a misspelled control never silently falls back
    to a default — the failure mode where a run looks fine and answers a slightly
    different question than the one that was configured. It is also what makes
    "a research question can never carry a URL" a property of the type rather
    than a habit: there is no field to put one in, and inventing one raises.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(
        min_length=1,
        max_length=8_000,
        description="Sub-question answerable by a single retrieval call.",
    )
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        ge=1,
        le=50,
        description="Upper bound on returned passages; the budget for one step's evidence.",
    )


class RetrieveResult(BaseModel):
    """What one retrieval call produced.

    ``backend`` is recorded per call rather than per run because the fake and the
    HTTP backend can serve the same loop, and a trace that does not say which one
    answered cannot explain a difference between two runs. Empty is a result, not
    an error: "found nothing" is a field, not a tone.
    """

    question: str = Field(description="Sub-question this result answers.")
    backend: str = Field(description="Name of the retrieval backend that served the call.")
    passages: list[Passage] = Field(
        default_factory=list,
        description="Ranked evidence, best first. Empty is a valid answer.",
    )

    @property
    def is_empty(self) -> bool:
        """Return whether the call found no evidence at all."""
        return not self.passages


@runtime_checkable
class RetrievalBackend(Protocol):
    """One sub-question in, ranked evidence out.

    Everything the agent knows about the world arrives through this method.
    Structural, like :class:`~agentic_rag.tools.base.Tool`: the tool needs a
    search and a name to record, and nothing about where the passages came from.
    That is what lets a free deterministic stand-in and a real service be
    interchangeable without the loop noticing.

    Deliberately narrow. A backend that knows *why* it found nothing — the HTTP
    one does — exposes that on its own type rather than here, because widening
    this protocol would make every backend answer a question only one of them
    can answer.
    """

    @property
    def name(self) -> str:
        """Return the identifier recorded on every result this backend serves."""

    def search(self, sub_question: str, *, top_k: int) -> Sequence[Passage]:
        """Return up to ``top_k`` passages for ``sub_question``, best first."""


class Document(BaseModel):
    """One passage of a local corpus, before a query gives it a rank.

    Rank is a property of a search, not of a document, so it is absent here and
    assigned by :meth:`FakeRetrievalBackend.search`.
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=1)
    source_path: str
    text: str
    title: str | None = None
    heading_path: str | None = None


DEFAULT_CORPUS: Final[tuple[Document, ...]] = (
    Document(
        chunk_id="hybrid-retrieval-1",
        source_path="docs/retrieval.md",
        title="Retrieval",
        heading_path="Retrieval > Hybrid search",
        text=(
            "Hybrid retrieval runs a dense vector search and a sparse keyword search over "
            "the same corpus and fuses the two rankings with reciprocal rank fusion, so a "
            "query that only one of them understands still returns evidence."
        ),
    ),
    Document(
        chunk_id="reranking-1",
        source_path="docs/retrieval.md",
        title="Retrieval",
        heading_path="Retrieval > Reranking",
        text=(
            "A cross-encoder reranker reads the query and a candidate passage together and "
            "reorders the shortlist. It costs far more per pair than the retriever, which "
            "is why it runs over tens of candidates instead of the whole index."
        ),
    ),
    Document(
        chunk_id="citations-1",
        source_path="docs/answers.md",
        title="Answers",
        heading_path="Answers > Citations",
        text=(
            "Every citation marker in an answer resolves to a chunk that was actually "
            "retrieved. A marker resolving to nothing is dropped and reported, because a "
            "citation nobody can follow is decoration."
        ),
    ),
    Document(
        chunk_id="refusal-1",
        source_path="docs/answers.md",
        title="Answers",
        heading_path="Answers > Refusal",
        text=(
            "Refusal is a first-class outcome. When the retrieved evidence does not support "
            "an answer the pipeline says so and names the gap, instead of padding thin "
            "evidence with parametric memory."
        ),
    ),
    Document(
        chunk_id="chunking-1",
        source_path="docs/ingest.md",
        title="Ingest",
        heading_path="Ingest > Chunking",
        text=(
            "Chunking splits a document on its heading structure before it splits on size, "
            "so a chunk carries the heading path it came from and a retrieved passage can "
            "be traced back to its place in the source."
        ),
    ),
)
"""The committed corpus. Five short passages, enough to exercise ranking and misses."""

class FakeRetrievalBackend:
    """Deterministic in-process backend over the committed corpus.

    Ranking is lexical overlap between the sub-question and the document, ties
    broken by corpus order. That makes multi-step behaviour observable — a
    narrower sub-question retrieves different passages than the original question
    did — without pretending to be a retrieval quality result. A sub-question
    sharing no term with the corpus returns nothing, which is the case the loop
    most needs to handle and the one a backend that always returns its top five
    would hide.
    """

    name = "fake"

    def __init__(self, documents: Sequence[Document] | None = None) -> None:
        """Build the backend over ``documents``, or over the committed corpus."""
        self._documents: tuple[Document, ...] = tuple(
            DEFAULT_CORPUS if documents is None else documents
        )

    @property
    def documents(self) -> tuple[Document, ...]:
        """Return the corpus this backend searches."""
        return self._documents

    def search(self, sub_question: str, *, top_k: int) -> list[Passage]:
        """Return up to ``top_k`` passages overlapping ``sub_question``, best first.

        Args:
            sub_question: Sub-question to score documents against.
            top_k: Upper bound on the number of passages returned.

        Returns:
            Ranked passages, or an empty list when nothing overlaps.
        """
        terms = keyword_terms(sub_question)
        scored: list[tuple[int, int, Document]] = []
        for position, document in enumerate(self._documents):
            haystack = f"{document.title or ''} {document.heading_path or ''} {document.text}"
            overlap = len(terms & keyword_terms(haystack))
            if overlap:
                scored.append((-overlap, position, document))
        scored.sort()
        return [
            Passage(
                chunk_id=document.chunk_id,
                source_path=document.source_path,
                text=document.text,
                rank=rank,
                title=document.title,
                heading_path=document.heading_path,
            )
            for rank, (_, _, document) in enumerate(scored[:top_k], start=1)
        ]


class RetrieveTool:
    """Run one sub-question against a retrieval backend and return cited passages.

    The tool is the loop-facing surface; the backend is the outbound one. It owns
    the step's evidence budget and the record of which backend served the call,
    and nothing else: it does not rewrite the sub-question, and it does not
    reorder or filter what came back beyond the cap the caller asked for.
    """

    name = "retrieve"
    description = (
        "Run one sub-question against the retrieval boundary and return ranked passages "
        "with the ids needed to cite them. It does not plan, does not answer, and does "
        "not re-rank what the backend returned."
    )

    def __init__(self, backend: RetrievalBackend) -> None:
        """Bind the tool to the backend that will serve its calls."""
        self._backend = backend

    @property
    def backend_name(self) -> str:
        """Return the name of the bound backend, as recorded on every result."""
        return self._backend.name

    def run(self, request: RetrieveRequest) -> RetrieveResult:
        """Retrieve evidence for one sub-question.

        Args:
            request: The validated sub-question and its evidence budget.

        Returns:
            The passages the backend returned, capped at ``request.top_k``.

        Raises:
            ToolError: The backend could not produce a result.
        """
        passages = self._backend.search(request.question, top_k=request.top_k)
        return RetrieveResult(
            question=request.question,
            backend=self._backend.name,
            passages=list(passages[: request.top_k]),
        )


def build_retrieve_tool(backend: RetrievalBackend | None = None) -> RetrieveTool:
    """Build the retrieve tool, on the free path unless the hosted one is opted into.

    The address of the hosted service comes from the environment and from nowhere
    else. In particular it never comes from a research question: this function
    takes no URL, :class:`RetrieveRequest` has no field for one, and the tool is
    wired once, before any question is asked.

    Args:
        backend: Explicit backend. Supplied, the environment is not read at all,
            which is what tests want.

    Returns:
        A tool bound to ``backend``; otherwise to
        :class:`~agentic_rag.retrievers.http_p1.HttpRetrievalBackend` when
        ``PRODUCTION_RAG_URL`` is set to a non-empty value, and to
        :class:`FakeRetrievalBackend` in every other case.

    Raises:
        InvalidServiceUrlError: ``PRODUCTION_RAG_URL`` is set to something this
            client will not dial. Raised here, at wiring time, rather than
            degrading to the fake: a run that silently answered from a committed
            five-document fixture when the operator asked for a real corpus is a
            run whose results mean nothing, and nothing in the output would say
            so.
    """
    if backend is not None:
        return RetrieveTool(backend)
    base_url = os.environ.get(PRODUCTION_RAG_URL_ENV, "").strip()
    if base_url:
        return RetrieveTool(HttpRetrievalBackend(base_url))
    return RetrieveTool(FakeRetrievalBackend())


__all__ = [
    "DEFAULT_CORPUS",
    "DEFAULT_TOP_K",
    "PRODUCTION_RAG_URL_ENV",
    "Document",
    "FakeRetrievalBackend",
    "HttpRetrievalBackend",
    "Passage",
    "RetrievalBackend",
    "RetrieveRequest",
    "RetrieveResult",
    "RetrieveTool",
    "ToolError",
    "build_retrieve_tool",
]
