"""The retrieve tool's contract, exercised entirely offline.

No network and no credential: the default path is the in-process fake backend,
and the HTTP backend is driven through an httpx mock transport, so these tests
never need a production-rag instance running to pass.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from agentic_rag.tools import (
    DEFAULT_CORPUS,
    PRODUCTION_RAG_URL_ENV,
    Document,
    FakeRetrievalBackend,
    HttpRetrievalBackend,
    Passage,
    RetrievalBackend,
    RetrieveRequest,
    RetrieveResult,
    RetrieveTool,
    Tool,
    ToolError,
    build_retrieve_tool,
)

Handler = Callable[[httpx.Request], httpx.Response]

HYBRID_QUESTION = "How does hybrid retrieval fuse dense and sparse rankings?"
OFF_CORPUS_QUESTION = "What were quarterly revenues in Patagonia?"

CITATION = {
    "marker": 1,
    "chunk_id": "remote-1",
    "source_path": "docs/retrieval.md",
    "text": "Hybrid retrieval fuses dense and sparse rankings.",
    "rank": 1,
    "title": "Retrieval",
    "heading_path": "Retrieval > Hybrid search",
}
SECOND_CITATION = {**CITATION, "marker": 2, "chunk_id": "remote-2", "rank": 2}


def fake_tool() -> RetrieveTool:
    return RetrieveTool(FakeRetrievalBackend())


def mock_client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- the protocols ----------------------------------------------------------


def test_the_tool_satisfies_the_tool_protocol() -> None:
    tool = fake_tool()

    assert isinstance(tool, Tool)
    assert tool.name == "retrieve"
    assert "does not plan" in tool.description


def test_both_backends_satisfy_the_retrieval_boundary() -> None:
    assert isinstance(FakeRetrievalBackend(), RetrievalBackend)
    assert isinstance(HttpRetrievalBackend("http://retrieval.invalid"), RetrievalBackend)


# --- the fake backend -------------------------------------------------------


def test_the_committed_corpus_has_a_handful_of_distinct_passages() -> None:
    assert 3 <= len(DEFAULT_CORPUS) <= 5
    assert len({document.chunk_id for document in DEFAULT_CORPUS}) == len(DEFAULT_CORPUS)


def test_an_on_topic_question_returns_the_passage_that_overlaps_it_first() -> None:
    result = fake_tool().run(RetrieveRequest(question=HYBRID_QUESTION))

    assert isinstance(result, RetrieveResult)
    assert result.backend == "fake"
    assert result.question == HYBRID_QUESTION
    assert result.passages[0].chunk_id == "hybrid-retrieval-1"
    assert not result.is_empty


def test_passages_come_back_ranked_from_one_without_gaps() -> None:
    result = fake_tool().run(RetrieveRequest(question="evidence citation chunk answer retrieved"))

    assert [passage.rank for passage in result.passages] == list(range(1, len(result.passages) + 1))
    assert all(isinstance(passage, Passage) for passage in result.passages)


def test_a_narrower_sub_question_retrieves_different_passages() -> None:
    broad = fake_tool().run(RetrieveRequest(question="retrieval evidence answer", top_k=1))
    narrow = fake_tool().run(RetrieveRequest(question="chunking heading structure", top_k=1))

    assert broad.passages[0].chunk_id != narrow.passages[0].chunk_id
    assert narrow.passages[0].chunk_id == "chunking-1"


def test_a_question_sharing_no_term_with_the_corpus_returns_nothing() -> None:
    result = fake_tool().run(RetrieveRequest(question=OFF_CORPUS_QUESTION))

    assert result.passages == []
    assert result.is_empty


def test_top_k_caps_the_evidence_one_step_returns() -> None:
    question = "retrieval evidence citation chunk passage answer"

    capped = fake_tool().run(RetrieveRequest(question=question, top_k=2))
    uncapped = fake_tool().run(RetrieveRequest(question=question, top_k=50))

    assert len(capped.passages) == 2
    assert len(uncapped.passages) > 2
    assert [passage.chunk_id for passage in capped.passages] == [
        passage.chunk_id for passage in uncapped.passages[:2]
    ]


def test_the_same_question_retrieves_the_same_passages_every_time() -> None:
    first = fake_tool().run(RetrieveRequest(question=HYBRID_QUESTION))
    second = fake_tool().run(RetrieveRequest(question=HYBRID_QUESTION))

    assert first.model_dump() == second.model_dump()


def test_the_backend_can_be_given_its_own_corpus() -> None:
    backend = FakeRetrievalBackend(
        [Document(chunk_id="only-1", source_path="notes.md", text="polar bears eat seals")]
    )

    result = RetrieveTool(backend).run(RetrieveRequest(question="what do polar bears eat"))

    assert [passage.chunk_id for passage in result.passages] == ["only-1"]


def test_a_retrieved_passage_is_frozen() -> None:
    passage = fake_tool().run(RetrieveRequest(question=HYBRID_QUESTION)).passages[0]

    with pytest.raises(ValidationError):
        passage.text = "something else"


# --- request validation -----------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "valid", "top_k": 0},
        {"question": "valid", "top_k": 51},
        {"question": "valid", "topk": 3},
    ],
)
def test_a_malformed_request_is_rejected_before_the_tool_runs(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RetrieveRequest(**kwargs)


# --- the opt-in HTTP backend ------------------------------------------------


def test_the_http_backend_posts_the_free_providers_to_the_query_route() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"answer": "a", "refused": False, "citations": [CITATION]})

    with mock_client(handler) as client:
        backend = HttpRetrievalBackend("http://retrieval.invalid/", client=client)
        passages = backend.search("hybrid retrieval", top_k=5)

    assert seen["url"] == "http://retrieval.invalid/v1/query"
    assert seen["body"] == {
        "question": "hybrid retrieval",
        "mode": "hybrid",
        "llm": "fake",
        "embedder": "fake",
    }
    assert [passage.chunk_id for passage in passages] == ["remote-1"]
    assert passages[0].heading_path == "Retrieval > Hybrid search"


def test_the_http_backend_reads_citations_and_ignores_the_generated_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answer": "A single-pass answer this agent must not treat as evidence.",
                "refused": False,
                "citations": [CITATION, SECOND_CITATION],
            },
        )

    with mock_client(handler) as client:
        tool = RetrieveTool(HttpRetrievalBackend("http://retrieval.invalid", client=client))
        result = tool.run(RetrieveRequest(question="q", top_k=1))

    assert [passage.chunk_id for passage in result.passages] == ["remote-1"]
    assert all("single-pass answer" not in passage.text for passage in result.passages)


def test_a_refusal_from_the_service_is_no_evidence_rather_than_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"answer": "I cannot answer", "refused": True, "citations": []},
        )

    with mock_client(handler) as client:
        tool = RetrieveTool(HttpRetrievalBackend("http://retrieval.invalid", client=client))
        result = tool.run(RetrieveRequest(question="anything"))

    assert result.is_empty
    assert result.backend == "production-rag"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, text="unavailable"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"citations": [{"chunk_id": "x"}], "refused": False}),
    ],
)
def test_a_service_that_cannot_be_read_raises_tool_error(response: httpx.Response) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    with mock_client(handler) as client:
        backend = HttpRetrievalBackend("http://retrieval.invalid", client=client)
        with pytest.raises(ToolError):
            backend.search("q", top_k=5)


def test_a_transport_failure_raises_tool_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with mock_client(handler) as client, pytest.raises(ToolError, match="did not answer"):
        HttpRetrievalBackend("http://retrieval.invalid", client=client).search("q", top_k=5)


# --- wiring -----------------------------------------------------------------


def test_the_default_build_stays_on_the_free_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PRODUCTION_RAG_URL_ENV, raising=False)

    assert build_retrieve_tool().backend_name == "fake"


def test_a_blank_environment_variable_does_not_opt_into_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PRODUCTION_RAG_URL_ENV, "   ")

    assert build_retrieve_tool().backend_name == "fake"


def test_setting_the_service_url_opts_into_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PRODUCTION_RAG_URL_ENV, "http://127.0.0.1:8000")

    assert build_retrieve_tool().backend_name == "production-rag"


def test_an_explicit_backend_wins_over_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PRODUCTION_RAG_URL_ENV, "http://127.0.0.1:8000")

    assert build_retrieve_tool(FakeRetrievalBackend()).backend_name == "fake"
