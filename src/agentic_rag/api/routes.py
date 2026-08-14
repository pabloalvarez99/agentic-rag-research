"""``POST /v1/research`` — the HTTP door into the loop.

The route does four things and nothing else: take the validated body, resolve the
service the application was built with, run it under the request's correlation id, and
echo that id on the response. Every decision about the run is upstream of it, in
:class:`~agentic_rag.api.service.ResearchService`; every decision about how a failure
looks is downstream of it, in the exception handlers. What is left here is plumbing, and
that is the point — a route with reasoning in it is reasoning the CLI does not get.

The handler is a plain ``def``, so FastAPI runs it in a worker thread and two requests
genuinely overlap. That is what makes the concurrency test meaningful rather than
decorative: the isolation it asserts is the absence of shared mutable state, and the
test exercises real parallelism to prove it.

Failure shapes are declared on the route rather than left to FastAPI's defaults, because
an OpenAPI document that names only the success case describes a service nobody can
write a client for.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Request, Response

from agentic_rag.agent.state import TraceEvent
from agentic_rag.api.compare import (
    COMPARE_PATH,
    CompareRequest,
    CompareResponse,
    compare_runs,
)
from agentic_rag.api.errors import ErrorResponse, RunNotFound
from agentic_rag.api.handlers import correlation_id
from agentic_rag.api.metrics import run_and_count
from agentic_rag.api.request_id import REQUEST_ID_HEADER
from agentic_rag.api.runs import RUNS_PATH, RunArtifact
from agentic_rag.api.schemas import ResearchRequest, ResearchResponse
from agentic_rag.api.service import ResearchService

RESEARCH_PATH: Final = "/v1/research"
"""The versioned route. The version is in the path so a second shape can coexist."""

TRACE_PATH: Final = "/v1/research/trace"
"""The same run, projected to its trace and offered as a file.

A trace is only worth having in the UI if it can leave the UI, and it is only worth
having in the API if a client can save it next to whatever it is being compared with.
"""

RUN_PATH: Final = f"{RUNS_PATH}/{{run_id}}"
"""One finished run, by the correlation id it was served under."""

RUN_TRACE_PATH: Final = f"{RUN_PATH}/trace.json"
"""The same run, projected to its trace and offered as a download."""

RUN_ARTIFACT_PATH: Final = f"{RUN_PATH}/run.json"
"""The full finished-run artifact as a downloadable JSON file."""

CONTENT_DISPOSITION: Final = "content-disposition"
"""Header that turns the JSON body into a download rather than a rendered page."""


def _safe_id_token(request_id: str) -> str:
    """Return a filename-safe token derived from a correlation id."""
    safe = "".join(
        character for character in request_id if character.isalnum() or character in "-_"
    )
    return safe or "export"


def trace_filename(request_id: str) -> str:
    """Return the download filename for the trace of ``request_id``.

    The correlation id is the only thing that distinguishes two exports of the same
    question, so it is what names the file. It is filtered to characters that are safe
    in a filename and in a header, because an id can be echoed from the caller.

    Args:
        request_id: Correlation id of the run being exported.

    Returns:
        A filename of the form ``trace-<id>.json``.
    """
    return f"trace-{_safe_id_token(request_id)}.json"


def run_filename(request_id: str) -> str:
    """Return the download filename for the full artifact of ``request_id``.

    Args:
        request_id: Correlation id of the run being exported.

    Returns:
        A filename of the form ``run-<id>.json``.
    """
    return f"run-{_safe_id_token(request_id)}.json"

SERVICE_STATE_KEY: Final = "research_service"
"""Attribute on ``app.state`` holding the service every request is served by."""

_ERROR_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    HTTPStatus.UNPROCESSABLE_ENTITY: {
        "model": ErrorResponse,
        "description": (
            "The request was rejected: a blank or oversized question, a bound outside its "
            "range, an unknown field, or an unknown retriever."
        ),
    },
    HTTPStatus.SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": (
            "`capability_missing` when the requested retriever is not configured in this "
            "deployment, or `backend_unavailable` when a configured backend failed the call. "
            "The free retriever is never substituted for one that was asked for explicitly."
        ),
    },
    HTTPStatus.INTERNAL_SERVER_ERROR: {
        "model": ErrorResponse,
        "description": "A defect in this service. Carries no traceback and no request data.",
    },
}
"""The failures a client has to be able to handle, named in the schema."""

_RUN_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    HTTPStatus.NOT_FOUND: {
        "model": ErrorResponse,
        "description": (
            "`not_found`: this process does not hold that run. The store is bounded, "
            "in-memory and not shared between instances, so an id can be absent because "
            "it never existed, because it was evicted, or because another instance "
            "served it."
        ),
    },
    HTTPStatus.INTERNAL_SERVER_ERROR: _ERROR_RESPONSES[HTTPStatus.INTERNAL_SERVER_ERROR],
}
"""What a fetch of a stored run can answer with besides the run."""


def get_service(request: Request) -> ResearchService:
    """Return the service this application was built with.

    Resolved from application state rather than constructed here, so a test builds an
    application around its own service and every request in that application is served
    by it — including one that arrives while another is still running.
    """
    service = getattr(request.app.state, SERVICE_STATE_KEY, None)
    if isinstance(service, ResearchService):
        return service
    raise RuntimeError("the application was built without a research service")


router = APIRouter(tags=["research"])


@router.post(
    RESEARCH_PATH,
    response_model=ResearchResponse,
    responses=_ERROR_RESPONSES,
    summary="Run one bounded research loop",
    response_description=(
        "The finished run: how it ended, the report, the citations its markers resolve to, "
        "the steps it spent, the full trace, and the correlation id."
    ),
)
def research(
    payload: ResearchRequest,
    request: Request,
    response: Response,
    service: Annotated[ResearchService, Depends(get_service)],
) -> ResearchResponse:
    """Research a question under a step budget and report how the run ended.

    A run that refuses or exhausts its budget is a **200**: it is a completed run with an
    honest terminal status, not a failed request. Only a request this service cannot
    serve at all is a non-2xx.

    Args:
        payload: The validated request.
        request: The incoming request, read for its correlation id.
        response: The outgoing response, whose correlation header is set here.
        service: The application's research service.

    Returns:
        The finished run, correlated to this request.
    """
    request_id = correlation_id(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    return run_and_count(request, service, payload, request_id=request_id)


def stored_run(service: ResearchService, run_id: str) -> RunArtifact:
    """Return the stored run, or raise the typed 404 that says why it is absent.

    Args:
        service: The application's research service.
        run_id: Correlation id of the run.

    Returns:
        The artifact.

    Raises:
        RunNotFound: This process does not hold that run.
    """
    artifact = service.runs.get(run_id)
    if artifact is None:
        raise RunNotFound(
            "no run with that id is held by this process; the run store is bounded, "
            "in-memory and not shared between instances, so a run can be absent because "
            "it was evicted or because another instance served it"
        )
    return artifact


@router.get(
    RUN_PATH,
    response_model=RunArtifact,
    responses=_RUN_RESPONSES,
    summary="Fetch one finished run by its correlation id",
    response_description=(
        "The stored run: the question, the backend, how it ended, why it stopped, the "
        "report, the citations, the notes it relied on, the steps it spent against its "
        "budget, and the full trace."
    ),
)
def get_run(
    run_id: str,
    request: Request,
    response: Response,
    service: Annotated[ResearchService, Depends(get_service)],
) -> RunArtifact:
    """Return one finished run.

    The artifact is what makes a run reviewable after the response that produced it is
    gone: an id can be pasted into an issue, and whoever opens it reads the same report,
    the same citations and the same trace — not a re-run that is merely expected to
    match.

    ``stop_reason`` is a field here rather than something to dig out of the terminal
    ``stop`` event. Everything else is exactly what the run recorded.

    Args:
        run_id: Correlation id of the run.
        request: The incoming request, read for its correlation id.
        response: The outgoing response, whose correlation header is set here.
        service: The application's research service.

    Returns:
        The stored run.
    """
    response.headers[REQUEST_ID_HEADER] = correlation_id(request)
    return stored_run(service, run_id)


@router.get(
    RUN_TRACE_PATH,
    response_model=list[TraceEvent],
    responses=_RUN_RESPONSES,
    summary="Download the trace of one finished run",
    response_description=(
        "That run's trace, oldest event first and ending in 'stop', served as a JSON "
        "attachment."
    ),
)
def get_run_trace(
    run_id: str,
    request: Request,
    response: Response,
    service: Annotated[ResearchService, Depends(get_service)],
) -> list[TraceEvent]:
    """Serve one stored run's trace as a file.

    This is the contract the result page's download button uses. The file is the run
    that was performed, read from the store — not a second run of the same question that
    is assumed to be identical. The distinction only shows up on the day it stops being
    true, which is the day it matters.

    Args:
        run_id: Correlation id of the run.
        request: The incoming request, read for its correlation id.
        response: The outgoing response, whose correlation and download headers are set.
        service: The application's research service.

    Returns:
        Every event of the run, oldest first.
    """
    response.headers[REQUEST_ID_HEADER] = correlation_id(request)
    response.headers[CONTENT_DISPOSITION] = f'attachment; filename="{trace_filename(run_id)}"'
    return list(stored_run(service, run_id).trace)


@router.get(
    RUN_ARTIFACT_PATH,
    response_model=RunArtifact,
    responses=_RUN_RESPONSES,
    summary="Download one finished run as a JSON file",
    response_description=(
        "The full stored artifact — question, stop reason, steps, notes, citations, "
        "report, and trace — served as a JSON attachment a reviewer can keep after the "
        "in-memory id is gone."
    ),
)
def get_run_artifact_file(
    run_id: str,
    request: Request,
    response: Response,
    service: Annotated[ResearchService, Depends(get_service)],
) -> RunArtifact:
    """Serve one stored run as a downloadable file.

    The file is the durable hand-off for compare: after a serverless recycle the id is
    gone, but the JSON still carries every field ``POST /v1/runs/compare`` needs.

    Args:
        run_id: Correlation id of the run.
        request: The incoming request, read for its correlation id.
        response: The outgoing response, whose correlation and download headers are set.
        service: The application's research service.

    Returns:
        The stored artifact.
    """
    response.headers[REQUEST_ID_HEADER] = correlation_id(request)
    response.headers[CONTENT_DISPOSITION] = f'attachment; filename="{run_filename(run_id)}"'
    return stored_run(service, run_id)


@router.post(
    COMPARE_PATH,
    response_model=CompareResponse,
    responses={
        HTTPStatus.UNPROCESSABLE_ENTITY: _ERROR_RESPONSES[HTTPStatus.UNPROCESSABLE_ENTITY],
        HTTPStatus.INTERNAL_SERVER_ERROR: _ERROR_RESPONSES[HTTPStatus.INTERNAL_SERVER_ERROR],
    },
    summary="Compare two finished-run payloads (not server ids)",
    response_description=(
        "A typed field-level diff of stop reason, steps, notes, citations, and the "
        "other audited fields. Empty when the payloads match. Never looks up a run by id."
    ),
)
def compare_run_payloads(
    payload: CompareRequest,
    request: Request,
    response: Response,
) -> CompareResponse:
    """Diff two complete run artifacts supplied in the body.

    Ids are deliberately not accepted. The store is bounded, in-memory, and not shared
    across serverless instances; a compare keyed on ids would 404 the day a reviewer
    needed it most. The payloads — usually two downloaded ``run-*.json`` files — are the
    source of truth.

    Args:
        payload: Left and right finished-run bodies.
        request: The incoming request, read for its correlation id.
        response: The outgoing response, whose correlation header is set here.

    Returns:
        The typed diff, byte-stable for a given pair of inputs.
    """
    response.headers[REQUEST_ID_HEADER] = correlation_id(request)
    return compare_runs(payload.left, payload.right)


@router.post(
    TRACE_PATH,
    response_model=list[TraceEvent],
    responses=_ERROR_RESPONSES,
    summary="Run one bounded research loop and download only its trace",
    response_description=(
        "The run's trace, oldest event first and ending in 'stop' — the same list "
        "`POST /v1/research` returns under `trace`, served as a JSON attachment."
    ),
)
def research_trace(
    payload: ResearchRequest,
    request: Request,
    response: Response,
    service: Annotated[ResearchService, Depends(get_service)],
) -> list[TraceEvent]:
    """Export the trace of one run as a file.

    Takes the same request as ``POST /v1/research`` and answers with the same events
    that run's ``trace`` carries — this is a projection of the existing response, not a
    second contract, and no event means anything here that it does not mean there.

    There is deliberately no stored "last trace" to fetch. A server-side slot holding the
    most recent run would be shared mutable state between requests: two callers exporting
    at once would race for it, and the second would download the first one's evidence.
    The run is performed for the export instead, which on the free path is deterministic
    — the same question under the same budget produces the same trace, so the file
    matches the page it was downloaded from.

    Args:
        payload: The validated request.
        request: The incoming request, read for its correlation id.
        response: The outgoing response, whose correlation and download headers are set.
        service: The application's research service.

    Returns:
        Every event of the run, oldest first.
    """
    request_id = correlation_id(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers[CONTENT_DISPOSITION] = (
        f'attachment; filename="{trace_filename(request_id)}"'
    )
    return list(run_and_count(request, service, payload, request_id=request_id).trace)
