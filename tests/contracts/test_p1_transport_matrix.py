"""Every way the retrieval service can answer badly, driven through a mock transport.

The happy path is one test in here. The rest are the reasons this adapter exists:
a service that is down, slow, rate-limiting, redirecting, answering with someone
else's contract, or answering with a body that is technically JSON and nothing
this client can use. Each one has to end in a typed :class:`ToolError` with a
stable slug, or in honest empty evidence — never in an httpx exception reaching
the agent loop, and never in a passage the service did not actually return.

No socket is opened and no service is needed: ``httpx.MockTransport`` answers
every request in-process, so this file runs identically on a laptop with no
Docker and in CI. That is deliberate — these are the tests that must never skip.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from agentic_rag.tools import (
    ERROR_BACKEND_UNAVAILABLE,
    ERROR_CONTRACT_MISMATCH,
    ERROR_PROVIDER,
    ERROR_RATE_LIMITED,
    ERROR_UNAUTHORIZED,
    ERROR_VALIDATION,
    EvidenceState,
    HttpRetrievalBackend,
    ToolError,
)
from agentic_rag.tools.http_p1 import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
)

Handler = Callable[[httpx.Request], httpx.Response]

BASE_URL = "http://retrieval.invalid"
ANSWER = "A single-pass answer from another model, which is never this agent's evidence."


def citation(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "marker": 1,
        "chunk_id": "chunk-1",
        "source_path": "docs/retrieval.md",
        "text": "Hybrid retrieval fuses dense and sparse rankings.",
        "rank": 1,
        "title": "Retrieval",
        "heading_path": "Retrieval > Hybrid search",
    }
    base.update(overrides)
    return base


def grounded(*citations: dict[str, Any]) -> dict[str, Any]:
    return {"answer": ANSWER, "refused": False, "citations": list(citations)}


def responds(response: httpx.Response) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    return handler


def backend(handler: Handler, **kwargs: Any) -> HttpRetrievalBackend:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpRetrievalBackend(BASE_URL, client=client, **kwargs)


def raises_tool_error(handler: Handler, **kwargs: Any) -> ToolError:
    with pytest.raises(ToolError) as caught:
        backend(handler, **kwargs).search("q", top_k=5)
    return caught.value


# --- the request this client sends ------------------------------------------


def test_the_request_pins_free_providers_a_route_a_mode_and_no_reranker() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json=grounded(citation()))

    client = backend(handler)
    client.search("hybrid retrieval", top_k=5)

    assert seen["method"] == "POST"
    assert seen["url"] == "http://retrieval.invalid/v1/query"
    assert seen["body"] == {
        "question": "hybrid retrieval",
        "mode": "hybrid",
        "rerank": "off",
        "llm": "fake",
        "embedder": "fake",
    }
    assert seen["headers"]["x-request-id"] == client.request_id
    assert seen["headers"]["accept"] == "application/json"


def test_the_sub_question_travels_in_the_body_and_never_in_the_url() -> None:
    seen: dict[str, Any] = {}
    hostile = "http://evil.invalid/?x=1 OR 1=1 #../../etc/passwd"

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["question"] = json.loads(request.content)["question"]
        return httpx.Response(200, json=grounded())

    backend(handler).search(hostile, top_k=5)

    assert seen["url"] == "http://retrieval.invalid/v1/query"
    assert seen["question"] == hostile


def test_a_deployment_with_another_prefix_is_dialled_at_that_prefix() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=grounded())

    backend(handler, api_prefix="api/v9/").search("q", top_k=5)

    assert seen["url"] == "http://retrieval.invalid/api/v9/query"


def test_omitting_mode_and_rerank_sends_neither_field() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=grounded())

    backend(handler, mode=None, rerank=None).search("q", top_k=5)

    assert seen["body"] == {"question": "q", "llm": "fake", "embedder": "fake"}


def test_a_correlation_id_is_stable_for_the_life_of_the_backend() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["X-Request-ID"])
        return httpx.Response(200, json=grounded())

    client = backend(handler)
    client.search("first", top_k=5)
    client.search("second", top_k=5)

    assert seen == [client.request_id, client.request_id]


def test_an_explicit_correlation_id_is_used_verbatim() -> None:
    assert backend(responds(httpx.Response(200, json=grounded())), request_id="run-42.a").request_id


@pytest.mark.parametrize(
    "request_id", ["", "has space", "has/slash", "x" * 129, "emoji-\U0001f600", "tab\there"]
)
def test_a_correlation_id_the_service_would_silently_replace_is_refused(request_id: str) -> None:
    with pytest.raises(ValueError, match="request_id must be"):
        HttpRetrievalBackend(BASE_URL, request_id=request_id)


@pytest.mark.parametrize("question", ["", "    ", "\n\t", "x" * 8_001])
def test_a_sub_question_the_service_would_reject_fails_before_it_is_sent(question: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=grounded())

    with pytest.raises(ToolError) as caught:
        backend(handler).search(question, top_k=5)

    assert caught.value.error_type == ERROR_VALIDATION
    assert "would reject this sub-question" in str(caught.value)
    assert calls == []


# --- a grounded answer ------------------------------------------------------


def test_a_grounded_answer_becomes_ranked_passages() -> None:
    body = grounded(
        citation(),
        citation(marker=2, chunk_id="chunk-2", rank=2, text="Reranking reorders a shortlist."),
    )

    outcome = backend(responds(httpx.Response(200, json=body))).query("q", top_k=5)

    assert [passage.chunk_id for passage in outcome.passages] == ["chunk-1", "chunk-2"]
    assert [passage.rank for passage in outcome.passages] == [1, 2]
    assert outcome.evidence_state is EvidenceState.GROUNDED
    assert outcome.refusal_reason is None
    assert outcome.citations_returned == 2


def test_the_generated_answer_never_becomes_evidence() -> None:
    body = grounded(citation())

    passages = backend(responds(httpx.Response(200, json=body))).search("q", top_k=5)

    assert all(ANSWER not in passage.text for passage in passages)
    assert not any("answer" in passage.model_dump() for passage in passages)


def test_citations_are_returned_in_rank_order_not_in_the_order_the_answer_mentioned_them() -> None:
    body = grounded(
        citation(marker=1, chunk_id="mentioned-first", rank=7),
        citation(marker=2, chunk_id="best-ranked", rank=1),
        citation(marker=3, chunk_id="middling", rank=4),
    )

    passages = backend(responds(httpx.Response(200, json=body))).search("q", top_k=2)

    assert [passage.chunk_id for passage in passages] == ["best-ranked", "middling"]
    assert [passage.rank for passage in passages] == [1, 4]


def test_a_unicode_source_path_survives_verbatim() -> None:
    path = "docs/estudios/informe-café-año2026.md"
    body = grounded(citation(source_path=path, title="Café", heading_path="Café > Año"))

    passage = backend(responds(httpx.Response(200, json=body))).search("q", top_k=5)[0]

    assert passage.source_path == path
    assert passage.title == "Café"


def test_optional_citation_fields_may_be_absent() -> None:
    lean = {k: v for k, v in citation().items() if k not in {"title", "heading_path"}}

    passage = backend(responds(httpx.Response(200, json=grounded(lean)))).search("q", top_k=5)[0]

    assert passage.title is None
    assert passage.heading_path is None


# --- top_k --------------------------------------------------------------------


@pytest.mark.parametrize(("top_k", "expected"), [(1, 1), (3, 3), (5, 5), (50, 12)])
def test_top_k_caps_the_evidence_and_keeps_the_best_ranked(top_k: int, expected: int) -> None:
    body = grounded(
        *(
            citation(marker=index, chunk_id=f"chunk-{index}", rank=index)
            for index in range(1, 13)
        )
    )

    outcome = backend(responds(httpx.Response(200, json=body))).query("q", top_k=top_k)

    assert len(outcome.passages) == expected
    assert [passage.rank for passage in outcome.passages] == list(range(1, expected + 1))
    assert outcome.citations_returned == 12


def test_a_top_k_of_zero_asks_for_nothing_and_gets_nothing() -> None:
    body = grounded(citation())

    outcome = backend(responds(httpx.Response(200, json=body))).query("q", top_k=0)

    assert outcome.passages == ()
    assert outcome.citations_returned == 1
    assert outcome.evidence_state is EvidenceState.GROUNDED


def test_an_oversized_citation_list_is_capped_rather_than_carried() -> None:
    body = grounded(
        *(
            citation(marker=index, chunk_id=f"chunk-{index}", rank=index, text="x" * 2_000)
            for index in range(1, 501)
        )
    )

    outcome = backend(responds(httpx.Response(200, json=body))).query("q", top_k=5)

    assert len(outcome.passages) == 5
    assert outcome.citations_returned == 500


def test_duplicate_citations_count_once_and_keep_the_best_rank() -> None:
    body = grounded(
        citation(marker=1, chunk_id="same", rank=9),
        citation(marker=2, chunk_id="same", rank=2),
        citation(marker=3, chunk_id="other", rank=5),
    )

    outcome = backend(responds(httpx.Response(200, json=body))).query("q", top_k=5)

    assert [(p.chunk_id, p.rank) for p in outcome.passages] == [("same", 2), ("other", 5)]
    assert outcome.citations_returned == 3


# --- honest emptiness -------------------------------------------------------


def test_a_refusal_is_empty_evidence_and_says_so() -> None:
    body = {"answer": "I cannot answer", "refused": True, "refusal_reason": "no_evidence"}

    outcome = backend(responds(httpx.Response(200, json=body))).query("q", top_k=5)

    assert outcome.passages == ()
    assert outcome.evidence_state is EvidenceState.UPSTREAM_REFUSED
    assert outcome.refusal_reason == "no_evidence"


def test_an_answer_that_cited_nothing_is_empty_evidence_and_is_not_a_refusal() -> None:
    outcome = backend(responds(httpx.Response(200, json=grounded()))).query("q", top_k=5)

    assert outcome.passages == ()
    assert outcome.evidence_state is EvidenceState.ANSWERED_WITHOUT_CITATIONS
    assert outcome.refusal_reason is None


def test_a_refusal_with_no_reason_field_is_still_a_refusal() -> None:
    body = {"answer": "", "refused": True}

    outcome = backend(responds(httpx.Response(200, json=body))).query("q", top_k=5)

    assert outcome.evidence_state is EvidenceState.UPSTREAM_REFUSED
    assert outcome.refusal_reason is None


def test_a_refusal_that_arrives_with_citations_anyway_still_yields_no_evidence() -> None:
    """Impossible at the pinned tag; a proxy or a later release can produce it."""
    body = {
        "answer": "I cannot answer",
        "refused": True,
        "refusal_reason": "no_evidence",
        "citations": [citation()],
    }

    outcome = backend(responds(httpx.Response(200, json=body))).query("q", top_k=5)

    assert outcome.passages == ()
    assert outcome.evidence_state is EvidenceState.UPSTREAM_REFUSED
    assert outcome.citations_returned == 1


def test_the_two_kinds_of_empty_are_distinguishable_from_the_outside() -> None:
    refused = backend(
        responds(httpx.Response(200, json={"answer": "", "refused": True}))
    ).query("q", top_k=5)
    uncited = backend(responds(httpx.Response(200, json=grounded()))).query("q", top_k=5)

    assert refused.passages == uncited.passages == ()
    assert refused.evidence_state is not uncited.evidence_state


# --- additive change upstream ------------------------------------------------


def test_new_response_and_citation_fields_are_ignored_rather_than_fatal() -> None:
    body = grounded(citation(score=0.91, embedding_model="bge-small", nested={"a": [1, 2]}))
    body["latency_ms"] = 42.5
    body["trace"] = {"nodes": [{"name": "retrieve"}]}

    passages = backend(responds(httpx.Response(200, json=body))).search("q", top_k=5)

    assert [passage.chunk_id for passage in passages] == ["chunk-1"]


# --- error statuses ----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "error_type", "fragment"),
    [
        (400, ERROR_VALIDATION, "malformed"),
        (401, ERROR_UNAUTHORIZED, "credential"),
        (403, ERROR_UNAUTHORIZED, "refused the request"),
        (404, ERROR_CONTRACT_MISMATCH, "no query route"),
        (422, ERROR_VALIDATION, "invalid"),
        (429, ERROR_RATE_LIMITED, "rate-limited"),
        (418, ERROR_CONTRACT_MISMATCH, "does not expect"),
        (500, ERROR_PROVIDER, "failed while answering"),
        (502, ERROR_BACKEND_UNAVAILABLE, "failing gateway"),
        (503, ERROR_BACKEND_UNAVAILABLE, "unavailable"),
        (504, ERROR_BACKEND_UNAVAILABLE, "timed out"),
    ],
)
def test_an_error_status_becomes_a_typed_tool_error(
    status: int, error_type: str, fragment: str
) -> None:
    error = raises_tool_error(responds(httpx.Response(status, text="whatever")))

    assert error.error_type == error_type
    assert fragment in str(error)
    assert str(status) in str(error)


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_a_redirect_is_refused_rather_than_followed(status: int) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(status, headers={"Location": "http://elsewhere.invalid/v1/query"})

    error = raises_tool_error(handler)

    assert error.error_type == ERROR_CONTRACT_MISMATCH
    assert "redirect" in str(error)
    assert seen == ["http://retrieval.invalid/v1/query"]


def test_a_200_that_is_html_from_a_captive_proxy_is_a_contract_mismatch() -> None:
    error = raises_tool_error(
        responds(httpx.Response(200, html="<html><body>Sign in to continue</body></html>"))
    )

    assert error.error_type == ERROR_CONTRACT_MISMATCH


# --- transport failures -------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadError("peer reset"),
        httpx.RemoteProtocolError("server disconnected"),
        httpx.TooManyRedirects("too many redirects"),
    ],
)
def test_a_transport_failure_becomes_a_tool_error(failure: httpx.HTTPError) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise failure

    error = raises_tool_error(handler)

    assert error.error_type == ERROR_BACKEND_UNAVAILABLE
    assert "did not answer" in str(error)


@pytest.mark.parametrize(
    "timeout",
    [
        httpx.ConnectTimeout("connect timed out"),
        httpx.ReadTimeout("read timed out"),
        httpx.PoolTimeout("pool timed out"),
    ],
)
def test_a_timeout_becomes_a_tool_error_that_says_it_timed_out(
    timeout: httpx.TimeoutException,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise timeout

    error = raises_tool_error(handler)

    assert error.error_type == ERROR_BACKEND_UNAVAILABLE
    assert "within the timeout" in str(error)


def test_a_failed_call_is_not_retried() -> None:
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError("connection refused")

    raises_tool_error(handler)

    assert len(attempts) == 1


def test_a_500_is_not_retried_either() -> None:
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(500, text="boom")

    raises_tool_error(handler)

    assert len(attempts) == 1


def test_the_request_carries_the_configured_connect_and_read_budget() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions["timeout"]
        return httpx.Response(200, json=grounded())

    backend(handler).search("q", top_k=5)

    assert seen["timeout"] == {
        "connect": DEFAULT_CONNECT_TIMEOUT,
        "read": DEFAULT_READ_TIMEOUT,
        "write": DEFAULT_READ_TIMEOUT,
        "pool": DEFAULT_CONNECT_TIMEOUT,
    }


def test_a_custom_budget_reaches_the_transport() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions["timeout"]
        return httpx.Response(200, json=grounded())

    backend(handler, connect_timeout=0.5, read_timeout=2.0).search("q", top_k=5)

    assert seen["timeout"] == {"connect": 0.5, "read": 2.0, "write": 2.0, "pool": 0.5}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"connect_timeout": 0},
        {"connect_timeout": -1.0},
        {"read_timeout": 0},
        {"read_timeout": -0.1},
        {"max_response_bytes": 0},
        {"max_response_bytes": -1},
    ],
)
def test_an_unbounded_budget_cannot_be_configured(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="positive"):
        HttpRetrievalBackend(BASE_URL, **kwargs)


# --- unreadable bodies --------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "not json at all",
        "",
        "{",
        '{"answer": "a", "refused": false,}',
        "[]",
        '"a string"',
        "null",
        "42",
    ],
)
def test_a_body_that_is_not_a_json_object_is_a_contract_mismatch(body: str) -> None:
    error = raises_tool_error(responds(httpx.Response(200, text=body)))

    assert error.error_type == ERROR_CONTRACT_MISMATCH


@pytest.mark.parametrize(
    "body",
    [
        {"answer": "a", "refused": "false"},
        {"answer": "a", "refused": 0},
        {"answer": "a", "refused": False, "citations": {}},
        {"answer": "a", "refused": False, "citations": [{"chunk_id": "x"}]},
        {"answer": "a", "refused": False, "citations": [citation(rank="1")]},
        {"answer": "a", "refused": False, "citations": [citation(rank=0)]},
        {"answer": "a", "refused": False, "citations": [citation(chunk_id="")]},
        {"answer": "a", "refused": False, "citations": [citation(chunk_id=None)]},
        {"answer": "a", "refused": False, "citations": [citation(text=None)]},
        {"answer": "a", "refused": False, "citations": [citation(marker="1")]},
        {"answer": "a", "refused": False, "citations": [citation(source_path=42)]},
        {"answer": "a", "refused": False, "citations": ["a string"]},
        {"answer": "a", "refused": False, "refusal_reason": 7},
    ],
)
def test_a_field_with_the_wrong_type_is_a_contract_mismatch(body: dict[str, Any]) -> None:
    error = raises_tool_error(responds(httpx.Response(200, json=body)))

    assert error.error_type == ERROR_CONTRACT_MISMATCH
    assert "cannot read" in str(error) or "expected a JSON object" in str(error)


def test_a_body_larger_than_the_bound_is_abandoned() -> None:
    body = grounded(citation(text="x" * 20_000))

    error = raises_tool_error(responds(httpx.Response(200, json=body)), max_response_bytes=1_024)

    assert error.error_type == ERROR_CONTRACT_MISMATCH
    assert "more than 1024 bytes" in str(error)


def test_a_body_just_under_the_bound_is_read() -> None:
    body = grounded(citation())
    size = len(json.dumps(body).encode())

    passages = backend(
        responds(httpx.Response(200, json=body)), max_response_bytes=size + 64
    ).search("q", top_k=5)

    assert [passage.chunk_id for passage in passages] == ["chunk-1"]


def test_an_endless_stream_is_cut_off_rather_than_accumulated() -> None:
    def endless() -> Any:
        while True:
            yield b"x" * 4_096

    error = raises_tool_error(responds(httpx.Response(200, content=endless())))

    assert error.error_type == ERROR_CONTRACT_MISMATCH
    assert "sent more than" in str(error)


# --- what an error is allowed to say -----------------------------------------


SENSITIVE = "internal-project-codename-nobody-wants-in-a-log"


@pytest.mark.parametrize(
    "handler",
    [
        responds(httpx.Response(500, text="boom")),
        responds(httpx.Response(503)),
        responds(httpx.Response(200, text="not json")),
        responds(httpx.Response(200, json={"answer": "a", "refused": "no"})),
    ],
)
def test_no_error_message_repeats_the_sub_question(handler: Handler) -> None:
    with pytest.raises(ToolError) as caught:
        backend(handler).search(SENSITIVE, top_k=5)

    assert SENSITIVE not in str(caught.value)


def test_a_locally_rejected_sub_question_is_not_echoed_into_the_error() -> None:
    with pytest.raises(ToolError) as caught:
        backend(responds(httpx.Response(200, json=grounded()))).search(SENSITIVE * 400, top_k=5)

    assert "codename" not in str(caught.value)
    assert "question: String should have at most 8000 characters" in str(caught.value)


def test_an_unreadable_body_is_reported_by_field_and_rule_not_by_value() -> None:
    body = {"answer": "a", "refused": False, "citations": [citation(text=SENSITIVE, rank="1")]}

    error = raises_tool_error(responds(httpx.Response(200, json=body)))

    assert SENSITIVE not in str(error)
    assert "citations.0.rank: Input should be a valid integer" in str(error)


def test_every_error_names_the_endpoint_it_was_talking_to() -> None:
    for handler in (
        responds(httpx.Response(503)),
        responds(httpx.Response(200, text="nope")),
        responds(httpx.Response(200, json={"answer": "a", "refused": "no"})),
    ):
        error = raises_tool_error(handler)
        assert "http://retrieval.invalid/v1/query" in str(error)
