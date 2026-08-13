"""The opt-in retrieval backend that speaks to a running production-rag instance.

This is the agent's only outbound surface, and everything about it is written
for the failure cases rather than for the happy one. A retrieval call that
returns nothing, a service that is down, a proxy that answers 429, a body that
is not the contract any more, and a base URL that should never have been dialled
are all *expected* events on this path; the loop above has a budget to spend and
cannot spend it waiting on an unbounded read.

What the adapter guarantees, and what each guarantee is protecting against:

======================  ======================================================
Guarantee               Failure it exists to prevent
======================  ======================================================
Free providers pinned   Opting into the service silently opting into a billed
                        model or a billed reranker.
Citations only          The inner service's generated answer becoming this
                        agent's evidence, i.e. paraphrasing another model.
Rank-ordered cap        Truncating a list ordered by *mention* and throwing
                        away the best-ranked evidence.
Bounded connect/read    A hung service consuming the whole run.
No retries              A "transient" failure being multiplied by every layer
                        that decided to be helpful about it.
No redirects            An address that resolves somewhere other than the
                        service the operator configured.
Bounded response size   A single response exhausting memory.
Typed errors            httpx exception types leaking into agent control flow.
======================  ======================================================

Every one of them is exercised by a mock transport in ``tests/contracts``; none
of them needs a service running to test.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Final
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentic_rag.tools.base import (
    ERROR_BACKEND_UNAVAILABLE,
    ERROR_CONTRACT_MISMATCH,
    ERROR_PROVIDER,
    ERROR_RATE_LIMITED,
    ERROR_UNAUTHORIZED,
    ERROR_VALIDATION,
    ToolError,
)
from agentic_rag.tools.p1_contract import (
    DEFAULT_API_PREFIX,
    REQUEST_ID_HEADER,
    REQUEST_ID_PATTERN,
    EvidenceState,
    P1Citation,
    P1QueryRequest,
    P1QueryResponse,
    QueryMode,
    RerankMode,
    query_path,
)
from agentic_rag.tools.passage import Passage
from agentic_rag.tools.service_url import ServiceUrl

BACKEND_NAME: Final = "production-rag"
"""Name recorded on every result this backend serves, and in the run's trace."""

DEFAULT_CONNECT_TIMEOUT: Final = 3.0
"""Seconds to wait for a TCP connection.

Short on purpose and separate from the read budget: a service that is not
listening fails immediately on a healthy network, so a long connect timeout buys
nothing and turns "wrong port in the environment" into a slow run instead of an
error.
"""

DEFAULT_READ_TIMEOUT: Final = 20.0
"""Seconds to wait for the response body.

Generous relative to connect, because a real hybrid retrieval with a rerank pass
is genuinely slow the first time a model loads. Still finite: an agent with a
step budget and an unbounded read has no budget.
"""

MAX_RESPONSE_BYTES: Final = 4 * 1024 * 1024
"""Largest response body this client will accumulate.

The body is read in chunks and abandoned the moment it crosses this line, so a
service that streams forever costs bounded memory rather than the process. Four
megabytes is far above any plausible answer with a dozen cited passages, which
is what makes crossing it a signal rather than a limit to tune.
"""

_STATUS_ERRORS: Final[dict[int, tuple[str, str]]] = {
    400: (ERROR_VALIDATION, "rejected the request as malformed"),
    401: (ERROR_UNAUTHORIZED, "requires a credential this client does not send"),
    403: (ERROR_UNAUTHORIZED, "refused the request"),
    404: (ERROR_CONTRACT_MISMATCH, "serves no query route at this address"),
    422: (ERROR_VALIDATION, "rejected the request body as invalid"),
    429: (ERROR_RATE_LIMITED, "rate-limited this client"),
    502: (ERROR_BACKEND_UNAVAILABLE, "is behind a failing gateway"),
    503: (ERROR_BACKEND_UNAVAILABLE, "is unavailable"),
    504: (ERROR_BACKEND_UNAVAILABLE, "timed out behind a gateway"),
}
"""Statuses worth naming individually. Anything else falls back by class."""


class RemoteQueryOutcome(BaseModel):
    """One completed query against production-rag, including why it found what it found.

    :meth:`HttpRetrievalBackend.search` narrows this to passages, because that is
    all the :class:`~agentic_rag.tools.retrieve.RetrievalBackend` protocol carries
    and widening the protocol would make every backend answer a question only
    this one can answer. The full outcome stays reachable through
    :meth:`HttpRetrievalBackend.query` for the two callers that need it: the
    live-integration check, which has to prove a refusal was a refusal, and an
    operator diagnosing why a run had no evidence.

    ``evidence_state`` is the field that carries the distinction the passage list
    cannot: an upstream refusal and an answer that cited nothing are both zero
    passages here and completely different problems there.
    """

    model_config = ConfigDict(frozen=True)

    passages: tuple[Passage, ...] = Field(
        default=(),
        description="Evidence, best-ranked first, capped at the caller's top_k.",
    )
    evidence_state: EvidenceState = Field(
        description="Whether the answer was grounded, refused, or served without citations.",
    )
    refusal_reason: str | None = Field(
        default=None,
        description="Upstream refusal code when it refused; None otherwise.",
    )
    citations_returned: int = Field(
        ge=0,
        description="Citations in the response before dedupe and the top_k cap.",
    )
    request_id: str = Field(
        description="Correlation id sent with the request; the id to grep for upstream.",
    )


class HttpRetrievalBackend:
    """Opt-in backend that queries a running production-rag instance.

    It reads ``citations`` and never the generated ``answer``: each citation is
    already a passage with a chunk id and a source path, while the answer is the
    inner service's single pass — treating it as evidence would make this agent a
    paraphraser of another model's output. ``refused: true`` is information, not
    a failure; it comes back as no evidence, which is a gap ``critique`` can name.

    Built once, at wiring time, from an address that is deployment configuration.
    No research question ever reaches the URL: the only inputs to a call are the
    sub-question, which becomes a JSON string field, and the evidence cap.
    """

    name = BACKEND_NAME

    def __init__(
        self,
        base_url: str,
        *,
        api_prefix: str = DEFAULT_API_PREFIX,
        mode: QueryMode | None = "hybrid",
        rerank: RerankMode | None = "off",
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        request_id: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        """Point the backend at *base_url* and fix the terms of every call it makes.

        Args:
            base_url: Root of the instance, e.g. ``http://127.0.0.1:8000``.
                Validated on the way in; see
                :class:`~agentic_rag.tools.service_url.ServiceUrl`.
            api_prefix: The deployment's versioned route prefix. Configurable
                upstream, so it is configurable here rather than hard-coded.
            mode: Retrieval mode to ask for. ``hybrid`` by default because that is
                what the service is for and what its own default config selects;
                ``None`` omits the field and takes the deployment's setting, which
                is the honest choice against a collection with no sparse vectors.
            rerank: Rerank setting to ask for. ``off`` by default, and that
                default is load-bearing: omitting the field selects the
                deployment's ``auto``, which resolves to a hosted reranker on any
                deployment configured for one. A retrieval client must not be able
                to spend another service's budget by staying quiet.
            connect_timeout: Seconds to wait for the connection.
            read_timeout: Seconds to wait for the body.
            max_response_bytes: Bytes to accumulate before abandoning a response.
            request_id: Correlation id sent on every call, so this agent's trace
                and the service's access log describe the same request. Omitted, a
                UUID4 is minted for the life of the backend, which is the life of
                one wiring — every step of a run then carries one id.
            client: Caller-owned client. Supplied, it is used and never closed
                here, and this backend still pins the timeout and the
                no-redirect rule per request; its transport-level retry policy,
                however, belongs to whoever built it. Omitted, one client is
                created and closed per call, with retries explicitly disabled.

        Raises:
            InvalidServiceUrlError: ``base_url`` is not an address this client
                will dial.
            ValueError: ``api_prefix`` names no version segment, a timeout or size
                bound is not positive, or ``request_id`` has a shape the service
                would silently replace.
        """
        self._url = ServiceUrl(base_url)
        self._route = query_path(api_prefix)
        self._mode = mode
        self._rerank = rerank
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("connect_timeout and read_timeout must both be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=read_timeout,
            pool=connect_timeout,
        )
        self._max_response_bytes = max_response_bytes
        self._request_id = _validated_request_id(request_id)
        self._client = client

    @property
    def query_url(self) -> str:
        """Return the fully qualified query endpoint this backend calls."""
        return self._url.join(self._route)

    @property
    def request_id(self) -> str:
        """Return the correlation id sent with every call this backend makes."""
        return self._request_id

    def search(self, sub_question: str, *, top_k: int) -> list[Passage]:
        """Return up to ``top_k`` passages for ``sub_question``, best-ranked first.

        Args:
            sub_question: Sub-question to send. It is transported as a JSON
                string field and never becomes part of the URL.
            top_k: Upper bound applied to the citations that come back.

        Returns:
            Ranked passages, empty when the service refused or cited nothing.

        Raises:
            ToolError: The service was unreachable, timed out, answered with an
                error status, or sent a body this client cannot read. The
                ``error_type`` slug says which.
        """
        return list(self.query(sub_question, top_k=top_k).passages)

    def query(self, sub_question: str, *, top_k: int) -> RemoteQueryOutcome:
        """Run one query and return its evidence together with why that is the evidence.

        Args:
            sub_question: Sub-question to send.
            top_k: Upper bound applied to the citations that come back.

        Returns:
            The passages and the upstream outcome that produced them.

        Raises:
            ToolError: As :meth:`search`.
        """
        payload = self._payload(sub_question)
        if self._client is not None:
            body = self._fetch(self._client, payload)
        else:
            transport = httpx.HTTPTransport(retries=0)
            with httpx.Client(timeout=self._timeout, transport=transport) as client:
                body = self._fetch(client, payload)
        return self._outcome(self._parse(body), top_k=top_k)

    def _payload(self, sub_question: str) -> dict[str, object]:
        """Build and locally validate the request body for *sub_question*.

        The error names the field and the rule it broke and never the value.
        Pydantic's own rendering embeds a snippet of the input, and a tool error
        is written into the run's trace: a sub-question is not a credential, but
        an adapter that copies its input into its error text is one paste away
        from being the component that logged one.
        """
        try:
            request = P1QueryRequest(
                question=sub_question,
                mode=self._mode,
                rerank=self._rerank,
            )
        except ValidationError as error:
            raise ToolError(
                f"{self.query_url} would reject this sub-question: {_field_problems(error)}",
                error_type=ERROR_VALIDATION,
            ) from error
        return request.to_payload()

    def _fetch(self, client: httpx.Client, payload: dict[str, object]) -> bytes:
        """Send one request and return the bounded response body.

        Redirects are not followed. A retrieval client that follows a redirect
        can be pointed at a host the operator never configured, and the only
        legitimate reason for one here — an ``http`` address that should have been
        ``https`` — is fixed by correcting the environment, not by chasing it.
        """
        headers = {REQUEST_ID_HEADER: self._request_id, "Accept": "application/json"}
        try:
            with client.stream(
                "POST",
                self.query_url,
                json=payload,
                headers=headers,
                timeout=self._timeout,
                follow_redirects=False,
            ) as response:
                if response.status_code != httpx.codes.OK:
                    raise self._status_error(response.status_code)
                return self._read_bounded(response)
        except httpx.TimeoutException as error:
            raise ToolError(
                f"{self.query_url} did not answer within the timeout: {error!r}",
                error_type=ERROR_BACKEND_UNAVAILABLE,
            ) from error
        except httpx.HTTPError as error:
            raise ToolError(
                f"{self.query_url} did not answer: {error!r}",
                error_type=ERROR_BACKEND_UNAVAILABLE,
            ) from error

    def _status_error(self, status_code: int) -> ToolError:
        """Map an HTTP status onto a typed tool error with a stable slug."""
        named = _STATUS_ERRORS.get(status_code)
        if named is not None:
            error_type, description = named
        elif 300 <= status_code < 400:
            error_type = ERROR_CONTRACT_MISMATCH
            description = "answered with a redirect, which this client does not follow"
        elif status_code >= 500:
            error_type = ERROR_PROVIDER
            description = "failed while answering"
        else:
            error_type = ERROR_CONTRACT_MISMATCH
            description = "answered with a status this client does not expect"
        return ToolError(
            f"{self.query_url} {description} (HTTP {status_code})",
            error_type=error_type,
        )

    def _read_bounded(self, response: httpx.Response) -> bytes:
        """Accumulate the body, abandoning it if it crosses the size bound."""
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self._max_response_bytes:
                raise ToolError(
                    f"{self.query_url} sent more than {self._max_response_bytes} bytes",
                    error_type=ERROR_CONTRACT_MISMATCH,
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _parse(self, body: bytes) -> P1QueryResponse:
        """Validate the body against the pinned contract, strictly."""
        try:
            document = json.loads(body)
        except ValueError as error:
            raise ToolError(
                f"{self.query_url} sent a body that is not JSON: {error}",
                error_type=ERROR_CONTRACT_MISMATCH,
            ) from error
        if not isinstance(document, dict):
            raise ToolError(
                f"{self.query_url} sent {type(document).__name__}, expected a JSON object",
                error_type=ERROR_CONTRACT_MISMATCH,
            )
        try:
            return P1QueryResponse.model_validate(document)
        except ValidationError as error:
            raise ToolError(
                f"{self.query_url} sent a body this client cannot read: {_field_problems(error)}",
                error_type=ERROR_CONTRACT_MISMATCH,
            ) from error

    def _outcome(self, response: P1QueryResponse, *, top_k: int) -> RemoteQueryOutcome:
        """Project a validated response onto passages plus the reason for them."""
        return RemoteQueryOutcome(
            passages=_to_passages(response.citations, top_k=top_k),
            evidence_state=response.evidence_state,
            refusal_reason=response.refusal_reason,
            citations_returned=len(response.citations),
            request_id=self._request_id,
        )


def _field_problems(error: ValidationError) -> str:
    """Summarise a validation failure as fields and rules, never as values.

    Args:
        error: The failure raised while validating a request or a response.

    Returns:
        A compact ``field: rule`` list. ``str(error)`` would be more detailed and
        would also carry ``input_value=...`` for every failed field — the payload
        of a sub-question, or a chunk of somebody's corpus — into a message that
        ends up in a trace, a log line and an exception report.
    """
    problems = []
    for detail in error.errors(include_url=False):
        location = ".".join(str(part) for part in detail["loc"]) or "<body>"
        problems.append(f"{location}: {detail['msg']}")
    return "; ".join(problems)


def _validated_request_id(request_id: str | None) -> str:
    """Return a correlation id the service will accept, or mint one.

    Args:
        request_id: Caller-supplied id, or ``None``.

    Returns:
        The id to send on every call.

    Raises:
        ValueError: The supplied id has a shape production-rag would reject and
            silently replace with one of its own. Failing here is the point: an
            id that was substituted upstream joins nothing, and nothing about the
            substitution is visible from this side.
    """
    if request_id is None:
        return str(uuid4())
    if not REQUEST_ID_PATTERN.match(request_id):
        raise ValueError(
            "request_id must be 1-128 characters of [A-Za-z0-9._:-]; "
            "production-rag replaces anything else with an id this client never sees"
        )
    return request_id


def _to_passages(citations: Sequence[P1Citation], *, top_k: int) -> tuple[Passage, ...]:
    """Turn citations into ranked, distinct evidence, capped at *top_k*.

    Three transformations, each fixing something the raw list does wrong for this
    caller:

    * **Ordered by rank.** Upstream returns citations in the order the answer
      first mentioned them and deliberately does not renumber markers, so the
      list is in mention order and ``rank`` is the retrieval position. Slicing
      mention order to ``top_k`` would drop rank 1 to keep whatever the model
      cited in its opening sentence.
    * **Distinct by chunk id.** Two markers resolving to one chunk cannot happen
      in v0.1.0 — markers map to distinct prompt blocks — but a proxy, a cache or
      a later release can produce it, and a duplicate would let one passage count
      twice towards the critic's sufficiency score. The best rank wins.
    * **Rank preserved, not renumbered.** The number a passage carries is the
      position the retrieval service put it in. Renumbering to 1..n here would
      make the agent's evidence disagree with the service's own ranking, and
      every debugging session on this path starts by lining those two up.

    Args:
        citations: Validated citations, in upstream order.
        top_k: Upper bound on returned passages. Zero or less returns nothing.

    Returns:
        Passages, best-ranked first.
    """
    if top_k <= 0:
        return ()
    best: dict[str, tuple[int, P1Citation]] = {}
    for position, citation in enumerate(citations):
        kept = best.get(citation.chunk_id)
        if kept is None or citation.rank < kept[1].rank:
            best[citation.chunk_id] = (position, citation)
    ordered = sorted(best.values(), key=lambda item: (item[1].rank, item[0]))
    return tuple(
        Passage(
            chunk_id=citation.chunk_id,
            source_path=citation.source_path,
            text=citation.text,
            rank=citation.rank,
            title=citation.title,
            heading_path=citation.heading_path,
        )
        for _, citation in ordered[:top_k]
    )


__all__ = [
    "BACKEND_NAME",
    "DEFAULT_CONNECT_TIMEOUT",
    "DEFAULT_READ_TIMEOUT",
    "MAX_RESPONSE_BYTES",
    "HttpRetrievalBackend",
    "RemoteQueryOutcome",
]
