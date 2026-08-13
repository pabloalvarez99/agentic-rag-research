"""The two doors answer the same thing, and this is what keeps them that way.

A CLI that reimplements a route is a second answer to what the agent does, and the
second one is always the one that is out of date. These cases compare the JSON the two
produce for the same question — success and failure — field by field, with only the
correlation id allowed to differ.

The comparison is done through the real loop over the in-process corpus, so it is
checking the whole path each door takes and not two calls into the same mock.
"""

from __future__ import annotations

import io
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentic_rag.api.service import ResearchService
from agentic_rag.main import create_app
from agentic_rag.research import main
from agentic_rag.tools.retrieve import PRODUCTION_RAG_URL_ENV

from .conftest import ANSWERABLE, OFF_CORPUS, RecordingFactory

THIN = "How does chunking work?"
CORRELATION = "parity-1"


def offline_service() -> ResearchService:
    """The real loop, pinned to the in-process backend."""
    return ResearchService(retriever_factory=RecordingFactory())


def over_http(**payload: Any) -> dict[str, Any]:
    """Return the body ``POST /v1/research`` produces for ``payload``."""
    with TestClient(create_app(offline_service())) as client:
        response = client.post("/v1/research", json=payload)
    body: dict[str, Any] = response.json()
    return body


def over_cli(*argv: str) -> dict[str, Any]:
    """Return the JSON the CLI writes to stdout for ``argv``."""
    stdout, stderr = io.StringIO(), io.StringIO()
    main(list(argv), service=offline_service(), stdout=stdout, stderr=stderr)
    payload: dict[str, Any] = json.loads(stdout.getvalue())
    return payload


def test_a_grounded_answer_is_identical_through_both_doors() -> None:
    http = over_http(question=ANSWERABLE, max_steps=3, top_k=5)
    cli = over_cli("--question", ANSWERABLE, "--max-steps", "3", "--top-k", "5")

    assert http.pop("request_id") != cli.pop("request_id")
    assert http == cli


def test_a_refusal_is_identical_through_both_doors() -> None:
    http = over_http(question=OFF_CORPUS, max_steps=3)
    cli = over_cli("--question", OFF_CORPUS, "--max-steps", "3")

    http.pop("request_id")
    cli.pop("request_id")
    assert http == cli


def test_an_exhausted_budget_is_identical_through_both_doors() -> None:
    http = over_http(question=THIN, max_steps=1, top_k=1)
    cli = over_cli("--question", THIN, "--max-steps", "1", "--top-k", "1")

    http.pop("request_id")
    cli.pop("request_id")
    assert http == cli


def test_both_doors_default_to_the_same_budget_and_backend() -> None:
    http = over_http(question=ANSWERABLE)
    cli = over_cli("--question", ANSWERABLE)

    http.pop("request_id")
    cli.pop("request_id")
    assert http == cli


def test_an_unconfigured_backend_fails_identically_through_both_doors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PRODUCTION_RAG_URL_ENV, raising=False)

    with TestClient(create_app(ResearchService())) as client:
        http = client.post(
            "/v1/research", json={"question": ANSWERABLE, "retriever": "http"}
        ).json()

    stdout, stderr = io.StringIO(), io.StringIO()
    main(
        ["--question", ANSWERABLE, "--retriever", "http"],
        service=ResearchService(),
        stdout=stdout,
        stderr=stderr,
    )
    cli = json.loads(stdout.getvalue())

    http.pop("request_id")
    cli.pop("request_id")
    assert http == cli


def test_a_caller_correlation_id_reaches_the_body_through_both_doors() -> None:
    with TestClient(create_app(offline_service())) as client:
        http = client.post(
            "/v1/research",
            json={"question": ANSWERABLE},
            headers={"X-Request-ID": CORRELATION},
        ).json()

    cli = over_cli("--question", ANSWERABLE, "--request-id", CORRELATION)

    assert http["request_id"] == CORRELATION
    assert cli["request_id"] == CORRELATION
    assert http == cli
