"""The adapter against a real production-rag instance, on the free path only.

The mock-transport suite proves the adapter handles what the contract says the
service can do. This file proves the contract is still true — that the document
the running instance publishes is the one the client was written against, that
the documented grounded question comes back as ranked evidence, and that the
documented unanswerable question comes back as an explicit refusal rather than a
confident guess.

Every request here pins ``llm=fake``, ``embedder=fake`` and ``rerank=off``, and
those are not decoration: at the tagged commit the route selects providers from
the request body, so this file cannot place a billed call even against a
deployment that has keys configured. The one test that sends a raw body sends it
to the same route with the same pinned providers.

Nothing here starts, stops or ingests anything. The stack is the caller's, and
``scripts/integration/verify_p1.ps1`` (or ``.sh``) is what starts one and tears
down exactly what it started.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agentic_rag.tools import (
    ERROR_CONTRACT_MISMATCH,
    EvidenceState,
    HttpRetrievalBackend,
    ToolError,
)
from agentic_rag.tools.p1_contract import (
    BILLABLE_RERANK_MODES,
    FREE_PROVIDERS,
    P1_TAG,
    REFUSAL_REASONS,
    verify_contract,
)

pytestmark = pytest.mark.integration

GROUNDED_QUESTION = "Why does hybrid search use reciprocal rank fusion?"
REFUSAL_QUESTION = "Who won the Antarctic underwater chess championship?"

TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=60.0, pool=5.0)


@pytest.fixture
def sent() -> list[dict[str, Any]]:
    """Collect every request body this test actually put on the wire."""
    return []


@pytest.fixture
def backend(base_url: str, sent: list[dict[str, Any]]) -> Any:
    """Return a backend whose outgoing bodies are recorded for later assertions."""

    def record(request: httpx.Request) -> None:
        sent.append(json.loads(request.content))

    client = httpx.Client(
        transport=httpx.HTTPTransport(retries=0),
        event_hooks={"request": [record]},
        timeout=TIMEOUT,
    )
    with client:
        yield HttpRetrievalBackend(
            base_url,
            read_timeout=60.0,
            request_id="agentic-rag-integration",
            client=client,
        )


# --- the instance under test -------------------------------------------------


def test_the_instance_is_the_release_this_client_was_written_against(base_url: str) -> None:
    health = httpx.get(f"{base_url.rstrip('/')}/health", timeout=TIMEOUT).json()

    assert health["status"] == "ok"
    assert health["version"] == P1_TAG.removeprefix("v"), (
        f"expected production-rag {P1_TAG}, instance reports {health['version']}"
    )


def test_the_live_contract_is_the_one_this_adapter_pins(base_url: str) -> None:
    spec = httpx.get(f"{base_url.rstrip('/')}/openapi.json", timeout=TIMEOUT).json()

    assert verify_contract(spec) == ()


def test_the_live_service_still_forbids_unknown_request_fields(base_url: str) -> None:
    response = httpx.post(
        f"{base_url.rstrip('/')}/v1/query",
        json={"question": "q", "llm": "fake", "embedder": "fake", "top_k": 3},
        timeout=TIMEOUT,
    )

    assert response.status_code == 422, (
        "the client pre-validates against extra='forbid'; a service that now accepts "
        "unknown fields would silently ignore a control this client thinks it sent"
    )


# --- the two documented questions --------------------------------------------


def test_the_documented_grounded_question_returns_ranked_evidence(backend: Any) -> None:
    outcome = backend.query(GROUNDED_QUESTION, top_k=5)

    assert outcome.evidence_state is EvidenceState.GROUNDED
    assert outcome.refusal_reason is None
    assert outcome.passages, "the demo corpus is supposed to answer this one"
    assert len({passage.chunk_id for passage in outcome.passages}) == len(outcome.passages)
    assert [p.rank for p in outcome.passages] == sorted(p.rank for p in outcome.passages)
    assert all(passage.text.strip() for passage in outcome.passages)
    assert all(passage.source_path for passage in outcome.passages)
    assert outcome.request_id == "agentic-rag-integration"


def test_the_documented_unanswerable_question_is_refused(backend: Any) -> None:
    outcome = backend.query(REFUSAL_QUESTION, top_k=5)

    assert outcome.evidence_state is EvidenceState.UPSTREAM_REFUSED
    assert outcome.passages == ()
    assert outcome.refusal_reason in REFUSAL_REASONS, (
        f"refusal_reason {outcome.refusal_reason!r} is outside the closed set at {P1_TAG}"
    )


def test_the_two_documented_questions_end_in_different_states(backend: Any) -> None:
    grounded = backend.query(GROUNDED_QUESTION, top_k=5)
    refused = backend.query(REFUSAL_QUESTION, top_k=5)

    assert grounded.evidence_state is not refused.evidence_state
    assert bool(grounded.passages) and not refused.passages


def test_top_k_bounds_the_live_evidence(backend: Any) -> None:
    capped = backend.query(GROUNDED_QUESTION, top_k=1)
    wide = backend.query(GROUNDED_QUESTION, top_k=10)

    assert len(capped.passages) == 1
    assert len(wide.passages) >= len(capped.passages)
    assert capped.passages[0].rank == min(passage.rank for passage in wide.passages)


# --- what the live path is allowed to spend ----------------------------------


def test_every_live_request_pinned_free_providers_and_no_reranker(
    backend: Any, sent: list[dict[str, Any]]
) -> None:
    backend.query(GROUNDED_QUESTION, top_k=3)
    backend.query(REFUSAL_QUESTION, top_k=3)

    assert len(sent) == 2
    for body in sent:
        assert body["llm"] in FREE_PROVIDERS
        assert body["embedder"] in FREE_PROVIDERS
        assert body["rerank"] == "off"
        assert body["rerank"] not in BILLABLE_RERANK_MODES
        assert set(body) <= {"question", "mode", "rerank", "llm", "embedder"}


def test_a_wrong_prefix_against_a_live_instance_is_a_typed_error(base_url: str) -> None:
    backend = HttpRetrievalBackend(base_url, api_prefix="/v99", read_timeout=30.0)

    with pytest.raises(ToolError) as caught:
        backend.search(GROUNDED_QUESTION, top_k=1)

    assert caught.value.error_type == ERROR_CONTRACT_MISMATCH
