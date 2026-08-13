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

from agentic_rag.api.errors import ErrorResponse
from agentic_rag.api.handlers import correlation_id
from agentic_rag.api.request_id import REQUEST_ID_HEADER
from agentic_rag.api.schemas import ResearchRequest, ResearchResponse
from agentic_rag.api.service import ResearchService

RESEARCH_PATH: Final = "/v1/research"
"""The versioned route. The version is in the path so a second shape can coexist."""

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
    return service.run(payload, request_id=request_id)
