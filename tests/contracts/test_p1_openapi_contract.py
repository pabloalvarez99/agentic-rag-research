"""The pinned production-rag contract, checked offline and checked for rot.

Two different things are verified here, and only the first one is obvious:

1. The adapter is compatible with the contract production-rag v0.1.0 publishes.
   That is ``verify_contract()`` against the frozen excerpt in ``fixtures/``.
2. ``verify_contract()`` can actually tell when it is not. A drift detector that
   returns "no problems" for every input passes the first check forever, which is
   the failure mode that matters: it would go on passing through the release that
   broke the client. So each mutation below deletes or changes exactly one thing
   the adapter depends on and asserts the report names it.

Nothing here imports production-rag or opens a socket. The fixture is the
contract as of the tag; the live half of the same check lives in
``tests/integration`` and runs the same function against ``/openapi.json``.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, get_args

import pytest

from agentic_rag.tools.p1_contract import (
    BILLABLE_RERANK_MODES,
    FREE_PROVIDERS,
    MAX_QUESTION_CHARS,
    P1_COMMIT,
    P1_REPOSITORY,
    P1_TAG,
    REFUSAL_REASONS,
    EvidenceState,
    P1QueryRequest,
    P1QueryResponse,
    QueryMode,
    RerankMode,
    query_path,
    verify_contract,
)

FIXTURE = Path(__file__).parent / "fixtures" / "p1-query-v0.1.0.openapi.json"

Mutation = Any


def load_spec() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return spec


def schemas(spec: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = spec["components"]["schemas"]
    return result


# --- provenance -------------------------------------------------------------


def test_the_fixture_records_where_it_came_from() -> None:
    provenance = load_spec()["x-provenance"]

    assert provenance["upstream_repository"] == P1_REPOSITORY
    assert provenance["upstream_tag"] == P1_TAG
    assert provenance["upstream_commit"] == P1_COMMIT
    assert provenance["captured"]
    assert provenance["generated_by"]


def test_the_source_derived_refusal_reasons_match_the_fixture_record() -> None:
    recorded = load_spec()["x-provenance"]["facts_not_visible_in_openapi"]["refusal_reasons"]

    assert tuple(recorded["value"]) == REFUSAL_REASONS
    assert recorded["source"].endswith("guardrails.py at the tag")


def test_the_fixture_captures_only_the_route_this_client_calls() -> None:
    spec = load_spec()

    assert list(spec["paths"]) == ["/v1/query"]
    assert set(schemas(spec)) == {"QueryRequest", "QueryResponse", "CitationOut", "QueryDebug"}


# --- the adapter against the pinned contract --------------------------------


def test_the_pinned_contract_reports_no_incompatibility() -> None:
    assert verify_contract(load_spec()) == ()


def test_every_field_the_client_sends_is_one_the_pinned_request_accepts() -> None:
    payload = P1QueryRequest(question="q", mode="hybrid", rerank="off").to_payload()
    request = schemas(load_spec())["QueryRequest"]

    assert set(payload) <= set(request["properties"])
    assert request["additionalProperties"] is False
    for field in ("llm", "embedder"):
        assert payload[field] in request["properties"][field]["enum"]


def test_the_rerank_value_the_client_pins_is_free_and_the_billed_one_is_not_sendable() -> None:
    upstream = schemas(load_spec())["QueryRequest"]["properties"]["rerank"]["anyOf"][0]["enum"]

    assert set(BILLABLE_RERANK_MODES) <= set(upstream)
    assert BILLABLE_RERANK_MODES.isdisjoint(get_args(RerankMode))
    with pytest.raises(ValueError, match="rerank"):
        P1QueryRequest(question="q", rerank="cohere")  # type: ignore[arg-type]


def test_the_free_providers_are_the_only_ones_the_request_model_allows() -> None:
    assert FREE_PROVIDERS == ("fake",)
    for field in ("llm", "embedder"):
        with pytest.raises(ValueError, match=field):
            P1QueryRequest(question="q", **{field: "openai"})  # type: ignore[arg-type]


def test_the_client_never_sends_a_mode_the_pinned_request_rejects() -> None:
    upstream = schemas(load_spec())["QueryRequest"]["properties"]["mode"]["anyOf"][0]["enum"]

    assert set(get_args(QueryMode)) <= set(upstream)


def test_the_question_bound_matches_the_pinned_schema() -> None:
    question = schemas(load_spec())["QueryRequest"]["properties"]["question"]

    assert question["maxLength"] == MAX_QUESTION_CHARS
    with pytest.raises(ValueError, match="at most"):
        P1QueryRequest(question="x" * (MAX_QUESTION_CHARS + 1))


# --- the projection the route actually serialises ----------------------------


def test_a_response_carrying_only_the_required_fields_is_readable() -> None:
    """``response_model_exclude_unset=True`` can omit citations and refusal_reason."""
    response = P1QueryResponse.model_validate({"answer": "a", "refused": False})

    assert response.citations == []
    assert response.refusal_reason is None
    assert response.evidence_state is EvidenceState.ANSWERED_WITHOUT_CITATIONS


def test_only_answer_and_refused_are_required_upstream() -> None:
    assert set(schemas(load_spec())["QueryResponse"]["required"]) == {"answer", "refused"}


def test_a_refusal_reason_outside_the_tagged_set_is_readable_and_flagged() -> None:
    known = P1QueryResponse.model_validate(
        {"answer": "", "refused": True, "refusal_reason": "no_evidence"}
    )
    unknown = P1QueryResponse.model_validate(
        {"answer": "", "refused": True, "refusal_reason": "budget_exhausted"}
    )

    assert known.has_known_refusal_reason
    assert not unknown.has_known_refusal_reason
    assert unknown.evidence_state is EvidenceState.UPSTREAM_REFUSED


# --- the verifier can fail ---------------------------------------------------


def drop_route(spec: dict[str, Any]) -> None:
    spec["paths"] = {"/v1/answer": spec["paths"]["/v1/query"]}


def drop_required_question(spec: dict[str, Any]) -> None:
    schemas(spec)["QueryRequest"]["required"] = []


def shrink_question(spec: dict[str, Any]) -> None:
    schemas(spec)["QueryRequest"]["properties"]["question"]["maxLength"] = 500


def drop_rerank_off(spec: dict[str, Any]) -> None:
    enum = schemas(spec)["QueryRequest"]["properties"]["rerank"]["anyOf"][0]["enum"]
    enum.remove("off")


def drop_fake_llm(spec: dict[str, Any]) -> None:
    schemas(spec)["QueryRequest"]["properties"]["llm"]["enum"] = ["openai"]


def drop_mode_field(spec: dict[str, Any]) -> None:
    del schemas(spec)["QueryRequest"]["properties"]["mode"]


def allow_extra_request_fields(spec: dict[str, Any]) -> None:
    schemas(spec)["QueryRequest"]["additionalProperties"] = True


def drop_citations(spec: dict[str, Any]) -> None:
    del schemas(spec)["QueryResponse"]["properties"]["citations"]


def drop_citation_items(spec: dict[str, Any]) -> None:
    del schemas(spec)["QueryResponse"]["properties"]["citations"]["items"]


def retype_rank(spec: dict[str, Any]) -> None:
    schemas(spec)["CitationOut"]["properties"]["rank"]["type"] = "string"


def drop_marker(spec: dict[str, Any]) -> None:
    del schemas(spec)["CitationOut"]["properties"]["marker"]


def unrequire_chunk_id(spec: dict[str, Any]) -> None:
    schemas(spec)["CitationOut"]["required"].remove("chunk_id")


def retype_refused(spec: dict[str, Any]) -> None:
    schemas(spec)["QueryResponse"]["properties"]["refused"]["type"] = "string"


def drop_refusal_reason(spec: dict[str, Any]) -> None:
    del schemas(spec)["QueryResponse"]["properties"]["refusal_reason"]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (drop_route, "no POST /v1/query"),
        (drop_required_question, "no longer requires 'question'"),
        (shrink_question, "accepts 500 characters"),
        (drop_rerank_off, "'rerank' no longer accepts: off"),
        (drop_fake_llm, "'llm' no longer accepts: fake"),
        (drop_mode_field, "no longer accepts a 'mode' field"),
        (allow_extra_request_fields, "no longer forbids unknown request fields"),
        (drop_citations, "no 'citations' array"),
        (drop_citation_items, "declares no item schema"),
        (retype_rank, "citation 'rank' is 'string', expected 'integer'"),
        (drop_marker, "citation no longer carries 'marker'"),
        (unrequire_chunk_id, "citation 'chunk_id' is no longer required"),
        (retype_refused, "no boolean 'refused'"),
        (drop_refusal_reason, "no longer carries 'refusal_reason'"),
    ],
)
def test_one_breaking_change_is_reported_by_name(mutate: Mutation, expected: str) -> None:
    spec = deepcopy(load_spec())

    mutate(spec)
    problems = verify_contract(spec)

    assert any(expected in problem for problem in problems), problems


@pytest.mark.parametrize(
    "spec",
    [
        {},
        {"paths": {}},
        {"paths": None},
        {"paths": {"/v1/query": {}}},
        {"paths": {"/v1/query": None}},
        {"paths": {"/v1/query": {"get": {}}}},
    ],
)
def test_a_document_with_no_query_route_is_reported_rather_than_crashing(
    spec: dict[str, Any],
) -> None:
    assert verify_contract(spec) == ("no POST /v1/query in the document",)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda spec: spec["paths"]["/v1/query"]["post"].pop("requestBody"), "no JSON request"),
        (lambda spec: spec["paths"]["/v1/query"]["post"].pop("responses"), "no JSON 200 schema"),
        (
            lambda spec: spec["paths"]["/v1/query"]["post"]["responses"].pop("200"),
            "no JSON 200 schema",
        ),
        (
            lambda spec: spec["components"]["schemas"].pop("QueryResponse"),
            "no JSON 200 schema",
        ),
    ],
)
def test_a_document_missing_a_whole_half_of_the_contract_is_reported(
    mutate: Mutation, expected: str
) -> None:
    spec = deepcopy(load_spec())

    mutate(spec)

    assert any(expected in problem for problem in verify_contract(spec)), verify_contract(spec)


def test_an_additive_upstream_change_is_not_a_break() -> None:
    spec = deepcopy(load_spec())

    schemas(spec)["QueryResponse"]["properties"]["latency_ms"] = {"type": "number"}
    schemas(spec)["CitationOut"]["properties"]["score"] = {"type": "number"}
    schemas(spec)["QueryRequest"]["properties"]["rerank"]["anyOf"][0]["enum"].append("voyage")

    assert verify_contract(spec) == ()


# --- the route the client dials ---------------------------------------------


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("/v1", "/v1/query"),
        ("v1", "/v1/query"),
        ("/v1/", "/v1/query"),
        ("  /v2  ", "/v2/query"),
        ("/api/v3", "/api/v3/query"),
    ],
)
def test_the_query_route_is_built_from_the_deployments_prefix(prefix: str, expected: str) -> None:
    assert query_path(prefix) == expected


@pytest.mark.parametrize("prefix", ["", "/", "//", "   "])
def test_a_prefix_naming_no_version_segment_is_refused(prefix: str) -> None:
    with pytest.raises(ValueError, match="must name a version segment"):
        query_path(prefix)


def test_verifying_against_the_wrong_prefix_reports_the_route_it_looked_for() -> None:
    problems = verify_contract(load_spec(), api_prefix="/v2")

    assert problems == ("no POST /v2/query in the document",)
