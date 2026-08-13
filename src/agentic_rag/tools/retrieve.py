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
* :class:`HttpRetrievalBackend` — opt-in, built only when ``PRODUCTION_RAG_URL``
  names a running production-rag instance. No test reaches for it, because no
  test should need a service started to pass.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from typing import Final, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentic_rag.tools.base import ToolError

PRODUCTION_RAG_URL_ENV: Final = "PRODUCTION_RAG_URL"
"""Environment variable that opts the tool into the hosted retrieval service."""

QUERY_PATH: Final = "/v1/query"
"""Versioned query route production-rag already publishes."""

DEFAULT_TOP_K: Final = 5
"""Passages one retrieval step returns unless the caller asks for another number."""


class Passage(BaseModel):
    """One retrieved chunk of evidence, with the identity needed to cite it.

    Text, a stable chunk id and a corpus-relative source path are the three
    fields a citation needs to be checkable by someone who does not trust the
    agent. Frozen, because a passage is what a backend returned: evidence that
    can be edited afterwards is evidence a citation cannot be checked against.
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=1, description="Stable identifier of the supporting chunk.")
    source_path: str = Field(description="Corpus-relative path of the document it came from.")
    text: str = Field(description="Passage text exactly as the backend returned it.")
    rank: int = Field(ge=1, description="Position of the passage in the ranking it arrived in.")
    title: str | None = Field(default=None, description="Source document title, when known.")
    heading_path: str | None = Field(
        default=None,
        description="Heading ancestry within the source document, when known.",
    )


class RetrieveRequest(BaseModel):
    """One sub-question to run against the retrieval boundary.

    Unknown fields are rejected so a misspelled control never silently falls back
    to a default — the failure mode where a run looks fine and answers a slightly
    different question than the one that was configured.
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

_WORD = re.compile(r"[a-z0-9]+")

_STOPWORD_TEXT: Final = (
    "a an the and or but if is are was were be been being do does did of on in to for "
    "from with by at as it its that this these those what which who whom how why when where"
)
"""Words carried by nearly every passage. Left in, they would score noise as overlap."""

_STOPWORDS: Final[frozenset[str]] = frozenset(_STOPWORD_TEXT.split())


def _terms(text: str) -> set[str]:
    """Return the scoring terms of a string: lowercased words, stopwords removed."""
    return {word for word in _WORD.findall(text.lower()) if word not in _STOPWORDS}


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
        terms = _terms(sub_question)
        scored: list[tuple[int, int, Document]] = []
        for position, document in enumerate(self._documents):
            haystack = f"{document.title or ''} {document.heading_path or ''} {document.text}"
            overlap = len(terms & _terms(haystack))
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


class _Citation(BaseModel):
    """One citation as production-rag serialises it."""

    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    source_path: str
    text: str
    rank: int = Field(ge=1)
    title: str | None = None
    heading_path: str | None = None


class _QueryEnvelope(BaseModel):
    """The part of ``POST /v1/query`` this backend consumes.

    Extra fields are ignored rather than forbidden: the service is free to grow
    its response, and a client that breaks on a new field turns an additive
    change upstream into an outage here.
    """

    model_config = ConfigDict(extra="ignore")

    citations: list[_Citation] = Field(default_factory=list)
    refused: bool = False


class HttpRetrievalBackend:
    """Opt-in backend that speaks to a running production-rag instance.

    It reads ``citations`` and ignores ``answer``: each citation is already a
    passage with a chunk id and a source path, while the generated answer is the
    inner service's single pass — treating it as evidence would make this agent a
    paraphraser of another model's output. ``refused: true`` is information, not a
    failure; it comes back as no evidence, which is a gap ``critique`` can name.

    The request pins the free providers on both sides, so opting into the service
    does not silently opt into a billed model. ``POST /v1/query`` publishes no
    ``top_k`` control, so the cap is applied to what came back — that trims the
    transfer, not the service's work, and closing the gap needs a parameter
    upstream.
    """

    name = "production-rag"

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        """Point the backend at ``base_url``.

        Args:
            base_url: Root of the production-rag instance, e.g. ``http://127.0.0.1:8000``.
            timeout: Seconds to wait for one query, used when this backend owns the
                client.
            client: Caller-owned client. Supplied, it is used and never closed here;
                omitted, one client is created and closed per call.
        """
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client

    @property
    def query_url(self) -> str:
        """Return the fully qualified query endpoint this backend calls."""
        return f"{self._base_url}{QUERY_PATH}"

    def search(self, sub_question: str, *, top_k: int) -> list[Passage]:
        """Query the instance and return its resolved citations as passages.

        Args:
            sub_question: Sub-question to send.
            top_k: Upper bound applied to the citations that come back.

        Returns:
            Ranked passages, empty when the service refused or cited nothing.

        Raises:
            ToolError: The service was unreachable, answered with an error status,
                or sent a body this backend cannot read.
        """
        if self._client is not None:
            return self._query(self._client, sub_question, top_k)
        with httpx.Client(timeout=self._timeout) as client:
            return self._query(client, sub_question, top_k)

    def _query(self, client: httpx.Client, sub_question: str, top_k: int) -> list[Passage]:
        """Run one request and map the response onto passages."""
        payload = {
            "question": sub_question,
            "mode": "hybrid",
            "llm": "fake",
            "embedder": "fake",
        }
        try:
            response = client.post(self.query_url, json=payload, timeout=self._timeout)
            response.raise_for_status()
            envelope = _QueryEnvelope.model_validate(response.json())
        except httpx.HTTPError as error:
            raise ToolError(f"{self.query_url} did not answer: {error}") from error
        except (ValueError, ValidationError) as error:
            raise ToolError(f"{self.query_url} sent an unreadable body: {error}") from error

        return [
            Passage(
                chunk_id=citation.chunk_id,
                source_path=citation.source_path,
                text=citation.text,
                rank=citation.rank,
                title=citation.title,
                heading_path=citation.heading_path,
            )
            for citation in envelope.citations[:top_k]
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

    Args:
        backend: Explicit backend. Supplied, the environment is not read at all,
            which is what tests want.

    Returns:
        A tool bound to ``backend``; otherwise to :class:`HttpRetrievalBackend`
        when ``PRODUCTION_RAG_URL`` is set to a non-empty value, and to
        :class:`FakeRetrievalBackend` in every other case.
    """
    if backend is not None:
        return RetrieveTool(backend)
    base_url = os.environ.get(PRODUCTION_RAG_URL_ENV, "").strip()
    if base_url:
        return RetrieveTool(HttpRetrievalBackend(base_url))
    return RetrieveTool(FakeRetrievalBackend())
