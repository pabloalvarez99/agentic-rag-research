"""The OpenAPI document, which is the only contract a client author actually reads.

A schema that names one success shape and leaves every failure to a generic default
describes a service nobody can write a client for: the cases a client has to branch on
are exactly the ones missing. These assertions pin the failure shapes to the route, and
pin the request's bounds into the document so a client can validate before it sends.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentic_rag.api.schemas import MAX_MAX_STEPS, MAX_QUESTION_CHARS, MAX_TOP_K
from agentic_rag.main import create_app

RESEARCH = "/v1/research"


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    with TestClient(create_app()) as client:
        document: dict[str, Any] = client.get("/openapi.json").json()
    return document


def component(schema: dict[str, Any], name: str) -> dict[str, Any]:
    resolved: dict[str, Any] = schema["components"]["schemas"][name]
    return resolved


def response_model(schema: dict[str, Any], status: str) -> str:
    reference: str = schema["paths"][RESEARCH]["post"]["responses"][status]["content"][
        "application/json"
    ]["schema"]["$ref"]
    return reference.rsplit("/", 1)[-1]


def test_the_route_is_documented(schema: dict[str, Any]) -> None:
    assert RESEARCH in schema["paths"]
    assert "post" in schema["paths"][RESEARCH]


def test_the_success_shape_is_named(schema: dict[str, Any]) -> None:
    assert response_model(schema, "200") == "ResearchResponse"
    assert set(component(schema, "ResearchResponse")["required"]) == {
        "status",
        "report",
        "steps_used",
        "request_id",
    }


def test_the_success_shape_carries_the_six_contract_fields(schema: dict[str, Any]) -> None:
    assert set(component(schema, "ResearchResponse")["properties"]) == {
        "status",
        "report",
        "citations",
        "steps_used",
        "trace",
        "request_id",
    }


@pytest.mark.parametrize("status", ["422", "500", "503"])
def test_every_important_failure_is_named_as_the_shared_envelope(
    schema: dict[str, Any], status: str
) -> None:
    assert response_model(schema, status) == "ErrorResponse"


def test_the_failure_envelope_documents_its_slugs(schema: dict[str, Any]) -> None:
    slugs = component(schema, "ErrorType")["enum"]

    assert {"validation_error", "capability_missing", "backend_unavailable"} <= set(slugs)


def test_the_request_bounds_are_in_the_document(schema: dict[str, Any]) -> None:
    request = component(schema, "ResearchRequest")["properties"]

    assert request["max_steps"]["maximum"] == MAX_MAX_STEPS
    assert request["top_k"]["maximum"] == MAX_TOP_K
    assert request["question"]["maxLength"] == MAX_QUESTION_CHARS


def test_unknown_fields_are_documented_as_refused(schema: dict[str, Any]) -> None:
    assert component(schema, "ResearchRequest")["additionalProperties"] is False


def test_the_retriever_choice_is_a_closed_set(schema: dict[str, Any]) -> None:
    assert component(schema, "RetrieverChoice")["enum"] == ["fake", "http"]


def test_the_status_enum_is_the_canonical_one(schema: dict[str, Any]) -> None:
    assert component(schema, "ResearchStatus")["enum"] == [
        "running",
        "done",
        "refused",
        "budget_exhausted",
        "degraded",
    ]


def test_the_description_disclaims_the_fake_backend(schema: dict[str, Any]) -> None:
    description = schema["info"]["description"]

    assert "no claim" in description.lower()
    assert "capability_missing" in description


def test_the_citation_shape_is_the_shared_one(schema: dict[str, Any]) -> None:
    assert set(component(schema, "Citation")["properties"]) == {
        "marker",
        "source_path",
        "chunk_id",
        "snippet",
        "start_line",
        "end_line",
    }
