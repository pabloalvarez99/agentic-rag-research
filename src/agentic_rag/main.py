"""Application factory, the liveness probe, and the wiring of the runtime surface.

``create_app`` is a factory rather than a module-level assembly so tests build their own
instance instead of importing shared state. Uvicorn and any container consume the
module-level ``app`` (``uvicorn agentic_rag.main:app``).

The factory takes the research service as an argument. That is the seam that keeps the
transport tests offline: a test passes a service built over its own runner or its own
retriever factory, and no request in that application can reach a network — not because
a test remembered to patch something, but because nothing in the wiring reads the
environment unless the default service is the one that was built.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

from agentic_rag import __version__
from agentic_rag.api.handlers import install_error_handlers
from agentic_rag.api.middleware import RequestIdMiddleware
from agentic_rag.api.routes import SERVICE_STATE_KEY
from agentic_rag.api.routes import router as research_router
from agentic_rag.api.service import ResearchService

SERVICE_NAME = "agentic-rag-research"

API_DESCRIPTION = """
Agentic RAG research agent: a bounded **plan → retrieve → critique** loop that answers
with citations resolving to retrieved passages, or refuses and says why.

`POST /v1/research` runs the loop. Its default retriever is a deterministic in-process
fixture over a small committed corpus: it makes the loop's control flow, budget
accounting, trace and refusal path exercisable with no credential and no network, and it
supports **no claim whatsoever about retrieval or answer quality**. Selecting
`retriever: "http"` requires a configured production-rag instance and fails with
`capability_missing` when there is none — the fixture is never substituted for a backend
that was asked for explicitly.

Every response carries `X-Request-ID`, echoed from the caller when it is safe to echo and
minted otherwise. Every failure is `{"error", "error_type", "request_id"}`.
""".strip()


class HealthResponse(BaseModel):
    """Liveness payload: the process is up and can serve requests.

    Deliberately free of dependency state. A liveness probe that fails because a
    downstream is unavailable makes the orchestrator restart a healthy process, which
    does not fix the downstream. Dependency state belongs in a readiness route, and that
    route arrives with the first dependency this service cannot run without — the
    retrieval backend is not one, because the free path needs none.
    """

    status: Literal["ok"] = Field(
        default="ok",
        description="Constant marker; the HTTP status code carries the real signal.",
    )
    service: str = Field(description="Logical service name.")
    version: str = Field(description="Installed package version.")


router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    """Report that the process is alive."""
    return HealthResponse(service=SERVICE_NAME, version=__version__)


def create_app(service: ResearchService | None = None) -> FastAPI:
    """Build the FastAPI application.

    Args:
        service: The service every request is served by. Omitted, the default one is
            built — the agent loop over the backend the caller names in each request.

    Returns:
        An application exposing the liveness probe, ``POST /v1/research``, and the
        OpenAPI document, with the correlation-id middleware and the error envelope
        installed.
    """
    app = FastAPI(
        title=SERVICE_NAME,
        version=__version__,
        description=API_DESCRIPTION,
        docs_url="/docs",
        openapi_url="/openapi.json",
        license_info={"name": "MIT", "identifier": "MIT"},
    )
    setattr(app.state, SERVICE_STATE_KEY, ResearchService() if service is None else service)
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(router)
    app.include_router(research_router)
    return app


app = create_app()
"""ASGI entrypoint consumed by uvicorn."""
