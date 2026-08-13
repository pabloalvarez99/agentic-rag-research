"""The production-rag query contract this agent was built against, pinned.

Provenance — every constant and every model below was read out of one tagged
checkout, not out of a summary:

* Repository: ``https://github.com/pabloalvarez99/production-rag``
* Tag: ``v0.1.0``  ·  Commit: ``678c5543baf0f4a723dc823de1f19162ba54b4a9``
* Request/response shapes: ``src/production_rag/api/schemas.py``
* Route, status codes and the ``response_model_exclude_unset`` projection:
  ``src/production_rag/api/routes/query.py``
* Correlation-id header and the shape it must have:
  ``src/production_rag/api/middleware.py``
* Route prefix (``/v1``, and that it is deployment-configurable):
  ``src/production_rag/config.py``
* Closed set of refusal reasons: ``src/production_rag/generation/guardrails.py``
* Citation ordering and marker renumbering:
  ``src/production_rag/generation/citations.py``

Four facts from that reading drive the adapter, and each one is a bug if it is
assumed instead of checked:

1. **The request rejects unknown fields** (``extra="forbid"``). A field this
   client invents is a 422, not a silently ignored extra, so the payload is
   built in exactly one place — :class:`P1QueryRequest` — and validated locally
   before it is sent.
2. **The route publishes no ``top_k``.** The evidence cap is applied to what
   came back. That trims the transfer, not the service's work, and closing the
   gap needs a parameter upstream.
3. **Citations come back in answer order, not rank order.** ``extract_citations``
   collects markers in order of first appearance and deliberately does not
   renumber them, so ``citations[0]`` is the first passage the answer mentioned
   and may carry ``rank: 7``. Truncating that list to ``top_k`` would throw away
   the best evidence and keep whatever the model happened to cite first.
4. **The response omits unset fields.** The route sets
   ``response_model_exclude_unset=True``, and only ``answer`` and ``refused``
   are required by the schema, so ``citations`` and ``refusal_reason`` may be
   absent from a perfectly valid body. Every field this client reads therefore
   has a default.

Nothing here imports production-rag. The dependency is an HTTP contract, and a
contract that needs the other project installed to be described is not a
contract — it is a shared library with extra steps.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Final, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

P1_REPOSITORY: Final = "https://github.com/pabloalvarez99/production-rag"
"""Upstream this adapter integrates with. Read-only from here; never vendored."""

P1_TAG: Final = "v0.1.0"
"""The released tag whose contract this module describes."""

P1_COMMIT: Final = "678c5543baf0f4a723dc823de1f19162ba54b4a9"
"""The commit ``v0.1.0`` points at, recorded so a drift report can name it."""

DEFAULT_API_PREFIX: Final = "/v1"
"""Default ``Settings.api_prefix``.

Deployment-configurable upstream (``API_PREFIX``), which is why the adapter
takes it as an argument instead of hard-coding one route string.
"""

QUERY_ROUTE: Final = "/query"
"""The versioned query route, appended to the API prefix."""

REQUEST_ID_HEADER: Final = "X-Request-ID"
"""Correlation header production-rag reads inbound and echoes outbound.

Sending it is what makes one line in this agent's trace and one line in the
retrieval service's access log provably the same request.
"""

REQUEST_ID_PATTERN: Final = re.compile(r"\A[A-Za-z0-9._:-]{1,128}\Z")
"""Shape an inbound correlation id must have to be trusted upstream.

Copied from the upstream middleware so a malformed id is rejected here, loudly,
instead of being silently replaced there — a substituted id joins nothing, and
the substitution is invisible from this side.
"""

MAX_QUESTION_CHARS: Final = 8_000
"""Upper bound the upstream request model enforces on ``question``."""

QueryMode = Literal["dense", "sparse", "hybrid"]
"""Retrieval modes the upstream request model accepts."""

RerankMode = Literal["off", "auto", "fake", "local"]
"""Rerank settings this client is willing to ask for.

Upstream also accepts ``cohere``. It is deliberately absent: it is the one value
that always costs money, and a retrieval client has no business spending another
service's budget. A deployment that wants a hosted reranker configures it and
the caller asks for ``auto``, which is an explicit local decision rather than a
default this client made for them.
"""

BILLABLE_RERANK_MODES: Final = frozenset({"cohere"})
"""Upstream rerank values that can place a billed call. Never sent from here."""

FREE_PROVIDERS: Final = ("fake",)
"""The credential-free ``llm``/``embedder`` values. The only ones sent."""

REFUSAL_REASONS: Final = (
    "no_evidence",
    "model_abstained",
    "no_citations",
    "empty_answer",
)
"""Every reason production-rag v0.1.0 can refuse for, from ``guardrails.py``.

A closed set upstream, so it can be branched on here. It is *not* part of the
OpenAPI document — ``refusal_reason`` is declared as a plain string — so this is
source-derived provenance and the live check reports an unknown value rather
than pretending the set is authoritative forever.
"""


class EvidenceState(StrEnum):
    """Why a query returned the evidence it did.

    Three outcomes reach this client as "no passages", and collapsing them would
    throw away the only signal that says which one happened:

    * ``GROUNDED`` — the answer cited retrieved chunks. Evidence is non-empty.
    * ``UPSTREAM_REFUSED`` — the guardrail declined to answer. The corpus does
      not support this sub-question; that is a gap a critique can name.
    * ``ANSWERED_WITHOUT_CITATIONS`` — an answer was served and nothing in it
      resolved to a chunk. Structurally identical to a refusal from here, and a
      completely different problem over there: the corpus may well contain the
      evidence, and the grounding pipeline did not attach it.

    All three still produce honest empty-or-real evidence. The agent never reads
    the generated answer, so an uncited answer is worth exactly zero passages —
    but the operator looking at why a run refused deserves to know which of the
    two zeroes they are looking at.
    """

    GROUNDED = "grounded"
    UPSTREAM_REFUSED = "upstream_refused"
    ANSWERED_WITHOUT_CITATIONS = "answered_without_citations"


class P1QueryRequest(BaseModel):
    """The request body, validated here before it is ever sent.

    Mirrors upstream ``QueryRequest`` including ``extra="forbid"``: a field this
    client invents is a 422 over there, and finding that out locally — at wiring
    time, in a unit test, with a readable error — is cheaper than finding it out
    against a running service.

    ``debug`` is knowingly not modelled. It exists upstream and returns per-node
    timings; this client has no use for them and asking for diagnostics it does
    not read is a larger response for nothing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_CHARS,
        description="Sub-question to run against the retrieval service.",
    )
    mode: QueryMode | None = Field(
        default=None,
        description="Retrieval mode. None omits the field and takes the deployment's default.",
    )
    rerank: RerankMode | None = Field(
        default=None,
        description="Rerank setting. None omits the field and takes the deployment's default.",
    )
    llm: Literal["fake"] = Field(
        default="fake",
        description="Generation provider. Pinned free: this client never bills another service.",
    )
    embedder: Literal["fake"] = Field(
        default="fake",
        description="Query embedder. Pinned free, and it must match how the corpus was ingested.",
    )

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON body to send, omitting the fields left unset.

        Returns:
            A mapping carrying only fields the upstream model declares. Omitted
            optional fields fall back to the deployment's configuration, which is
            not the same thing as sending ``null`` — upstream reads ``null`` as
            "use the default" too, but sending it states a preference this client
            does not have.
        """
        return self.model_dump(exclude_none=True)


class P1Citation(BaseModel):
    """One citation as production-rag serialises it.

    Validated strictly. A retrieval client that quietly coerces ``"3"`` into a
    rank of 3 hides the moment the upstream contract changed shape, and the
    symptom of that drift is a subtly wrong ranking rather than an error anyone
    can act on.

    ``marker`` is required by the upstream schema and is deliberately not mapped
    onto :class:`~agentic_rag.retrievers.passage.Passage`: it numbers a sentence
    in *their* answer, and this agent writes its own report with its own
    markers. It is validated so that a response missing it is recognised as a
    different contract, not as evidence.
    """

    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)

    marker: int = Field(ge=1, description="One-based ordinal of the marker in the P1 answer.")
    chunk_id: str = Field(min_length=1, description="Stable identifier of the supporting chunk.")
    source_path: str = Field(description="Corpus-relative source path, carried verbatim.")
    text: str = Field(description="Supporting passage exactly as it was shown to the model.")
    rank: int = Field(ge=1, description="Position of the passage in the retrieved ranking.")
    title: str | None = Field(default=None, description="Source document title, when known.")
    heading_path: str | None = Field(
        default=None,
        description="Heading ancestry within the source document, when known.",
    )


class P1QueryResponse(BaseModel):
    """The part of a ``POST /v1/query`` body this client consumes.

    Two configuration choices, each load-bearing:

    * ``extra="ignore"`` — the service is free to grow its response, and a client
      that breaks on a new field turns an additive change upstream into an outage
      here. This is also what keeps ``answer`` out: the generated answer is not
      declared, so it is structurally impossible for it to reach the loop as
      evidence. A comment saying "we ignore the answer" can be edited; a model
      that has no field for it cannot.
    * ``strict=True`` — every field this client *does* read must arrive with the
      declared type. Coercion is exactly the behaviour that lets a contract drift
      unnoticed for a release. ``citations`` is declared as a list rather than a
      tuple for that reason and no other: strict validation rejects a JSON array
      for a tuple field, and the model is frozen, so nothing is given up.

    Every field carries a default, because the route serialises with
    ``response_model_exclude_unset=True`` and the schema requires only ``answer``
    and ``refused``.
    """

    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)

    citations: list[P1Citation] = Field(
        default_factory=list,
        description="Resolved evidence, in the order the answer first mentioned it.",
    )
    refused: bool = Field(
        default=False,
        description="Whether the evidence guardrail declined to answer.",
    )
    refusal_reason: str | None = Field(
        default=None,
        description="Machine-readable refusal explanation; null or absent for grounded answers.",
    )

    @property
    def evidence_state(self) -> EvidenceState:
        """Classify why this response carries the citations it carries."""
        if self.refused:
            return EvidenceState.UPSTREAM_REFUSED
        if not self.citations:
            return EvidenceState.ANSWERED_WITHOUT_CITATIONS
        return EvidenceState.GROUNDED

    @property
    def has_known_refusal_reason(self) -> bool:
        """Return whether a refusal named a reason from the tagged closed set."""
        return self.refusal_reason in REFUSAL_REASONS


def query_path(api_prefix: str = DEFAULT_API_PREFIX) -> str:
    """Return the absolute query route under *api_prefix*.

    Args:
        api_prefix: The deployment's ``API_PREFIX``. Normalised the same way
            upstream normalises it — one leading slash, no trailing slash — so a
            prefix configured as ``v1/`` and one configured as ``/v1`` resolve to
            the same route instead of to two.

    Returns:
        The route to POST to, e.g. ``/v1/query``.

    Raises:
        ValueError: The prefix names no version segment. Upstream rejects ``/``
            at startup because the unversioned and versioned health routes would
            collide, so a client that accepted it would be dialling a route the
            service refuses to serve.
    """
    normalised = "/" + api_prefix.strip().strip("/")
    if normalised == "/":
        raise ValueError("api_prefix must name a version segment, for example '/v1'")
    return f"{normalised}{QUERY_ROUTE}"


def _resolve(schema: Mapping[str, Any], spec: Mapping[str, Any]) -> Mapping[str, Any]:
    """Follow a local ``$ref`` one level, returning the schema unchanged if none."""
    reference = schema.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/"):
        return schema
    node: Any = spec
    for part in reference.removeprefix("#/").split("/"):
        if not isinstance(node, Mapping) or part not in node:
            return {}
        node = node[part]
    return node if isinstance(node, Mapping) else {}


def _properties(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a schema's ``properties`` mapping, or an empty one."""
    properties = schema.get("properties")
    return properties if isinstance(properties, Mapping) else {}


def _enum_values(schema: Mapping[str, Any]) -> set[Any] | None:
    """Return the values a property accepts, looking inside ``anyOf`` branches.

    Returns:
        The union of every declared enum, or ``None`` when the property declares
        no enum at all — an unconstrained string accepts anything this client
        would send, which is compatibility, not a gap.
    """
    values: set[Any] = set()
    found = False
    for candidate in (schema, *(schema.get("anyOf") or [])):
        if not isinstance(candidate, Mapping):
            continue
        enum = candidate.get("enum")
        if isinstance(enum, Sequence) and not isinstance(enum, str | bytes):
            values.update(enum)
            found = True
    return values if found else None


_REQUIRED_CITATION_TYPES: Final = {
    "chunk_id": "string",
    "source_path": "string",
    "text": "string",
    "rank": "integer",
    "marker": "integer",
}
"""Citation fields the adapter reads, and the JSON types it reads them as.

``marker`` is here despite never becoming a passage: it is the field that makes
"citations arrive in answer order" a checkable statement rather than a comment,
and its disappearance would mean the ordering rationale needs re-deriving.
"""


def verify_contract(
    spec: Mapping[str, Any],
    *,
    api_prefix: str = DEFAULT_API_PREFIX,
) -> tuple[str, ...]:
    """Report every way *spec* would break this adapter.

    Runs against any OpenAPI document for a production-rag deployment: the
    frozen excerpt committed under ``tests/contracts/fixtures`` (offline, always),
    the document a locally installed upstream generates, or ``/openapi.json``
    fetched from the instance an integration run is about to talk to. One
    function, three sources, so "compatible" means the same thing in all three.

    It checks only what this client depends on. An upstream field it never reads
    can change freely — that is the point of an additive contract — and a report
    that fires on those is a report nobody reads.

    Args:
        spec: A parsed OpenAPI document.
        api_prefix: The prefix the deployment mounts its versioned routes under.

    Returns:
        Human-readable mismatches, empty when the document is compatible.
    """
    problems: list[str] = []
    route = query_path(api_prefix)

    paths = spec.get("paths")
    operation = paths.get(route) if isinstance(paths, Mapping) else None
    post = operation.get("post") if isinstance(operation, Mapping) else None
    if not isinstance(post, Mapping):
        return (f"no POST {route} in the document",)

    request = _resolve(_json_schema(post.get("requestBody")), spec)
    if not request:
        problems.append(f"POST {route} declares no JSON request schema")
    else:
        problems.extend(_verify_request(request, route))

    responses = post.get("responses")
    ok = responses.get("200") if isinstance(responses, Mapping) else None
    response = _resolve(_json_schema(ok), spec)
    if not response:
        problems.append(f"POST {route} declares no JSON 200 schema")
    else:
        problems.extend(_verify_response(response, spec, route))

    return tuple(problems)


def _json_schema(node: object) -> Mapping[str, Any]:
    """Return the ``application/json`` schema of a request body or response."""
    if not isinstance(node, Mapping):
        return {}
    content = node.get("content")
    if not isinstance(content, Mapping):
        return {}
    media = content.get("application/json")
    if not isinstance(media, Mapping):
        return {}
    schema = media.get("schema")
    return schema if isinstance(schema, Mapping) else {}


def _verify_request(request: Mapping[str, Any], route: str) -> list[str]:
    """Check that every field this client sends is one the request accepts."""
    problems: list[str] = []
    properties = _properties(request)
    required = set(request.get("required") or ())

    if "question" not in required:
        problems.append(f"{route} no longer requires 'question'")

    question = properties.get("question")
    max_length = question.get("maxLength") if isinstance(question, Mapping) else None
    if isinstance(max_length, int) and max_length < MAX_QUESTION_CHARS:
        problems.append(
            f"{route} 'question' accepts {max_length} characters, "
            f"below the {MAX_QUESTION_CHARS} this client allows"
        )

    sendable: dict[str, set[Any]] = {
        "mode": set(get_args(QueryMode)),
        "rerank": set(get_args(RerankMode)),
        "llm": set(FREE_PROVIDERS),
        "embedder": set(FREE_PROVIDERS),
    }
    for name, values in sendable.items():
        schema = properties.get(name)
        if not isinstance(schema, Mapping):
            problems.append(f"{route} no longer accepts a '{name}' field")
            continue
        accepted = _enum_values(schema)
        if accepted is None:
            continue
        missing = sorted(str(value) for value in values - accepted)
        if missing:
            problems.append(f"{route} '{name}' no longer accepts: {', '.join(missing)}")

    if request.get("additionalProperties") is not False:
        problems.append(
            f"{route} no longer forbids unknown request fields; "
            "the local pre-validation is now stricter than the service"
        )
    return problems


def _verify_response(
    response: Mapping[str, Any],
    spec: Mapping[str, Any],
    route: str,
) -> list[str]:
    """Check that every field this client reads is one the response can carry."""
    problems: list[str] = []
    properties = _properties(response)

    refused = properties.get("refused")
    if not isinstance(refused, Mapping) or refused.get("type") != "boolean":
        problems.append(f"{route} response has no boolean 'refused'")
    if "refusal_reason" not in properties:
        problems.append(f"{route} response no longer carries 'refusal_reason'")

    citations = properties.get("citations")
    if not isinstance(citations, Mapping) or citations.get("type") != "array":
        return [*problems, f"{route} response has no 'citations' array"]

    items = citations.get("items")
    citation = _resolve(items, spec) if isinstance(items, Mapping) else {}
    if not citation:
        return [*problems, f"{route} 'citations' declares no item schema"]

    citation_properties = _properties(citation)
    citation_required = set(citation.get("required") or ())
    for name, expected in _REQUIRED_CITATION_TYPES.items():
        schema = citation_properties.get(name)
        if not isinstance(schema, Mapping):
            problems.append(f"{route} citation no longer carries '{name}'")
            continue
        if schema.get("type") != expected:
            problems.append(
                f"{route} citation '{name}' is {schema.get('type')!r}, expected {expected!r}"
            )
        if name not in citation_required:
            problems.append(f"{route} citation '{name}' is no longer required")
    return problems


__all__ = [
    "BILLABLE_RERANK_MODES",
    "DEFAULT_API_PREFIX",
    "FREE_PROVIDERS",
    "MAX_QUESTION_CHARS",
    "P1_COMMIT",
    "P1_REPOSITORY",
    "P1_TAG",
    "QUERY_ROUTE",
    "REFUSAL_REASONS",
    "REQUEST_ID_HEADER",
    "REQUEST_ID_PATTERN",
    "EvidenceState",
    "P1Citation",
    "P1QueryRequest",
    "P1QueryResponse",
    "QueryMode",
    "RerankMode",
    "query_path",
    "verify_contract",
]
