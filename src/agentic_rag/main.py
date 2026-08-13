"""Application factory and the liveness probe.

``create_app`` is a factory rather than a module-level assembly so tests build
their own instance instead of importing shared state. Uvicorn and any container
consume the module-level ``app`` (``uvicorn agentic_rag.main:app``).

At this scaffold stage the only route is ``/health``. The agent loop described in
``docs/architecture.md`` is not implemented, and nothing here reads a credential.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

from agentic_rag import __version__

SERVICE_NAME = "agentic-rag-research"

API_DESCRIPTION = """
Agentic RAG research agent.

**Scaffold.** Only the liveness probe and the OpenAPI document exist. The
plan / retrieve / critique loop arrives with the milestones in
`docs/architecture.md`.
""".strip()


class HealthResponse(BaseModel):
    """Liveness payload: the process is up and can serve requests.

    Deliberately free of dependency state. A liveness probe that fails because a
    downstream is unavailable makes the orchestrator restart a healthy process,
    which does not fix the downstream. Dependency state belongs in a readiness
    route, and that route arrives with the first dependency.
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


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Returns:
        An application exposing the liveness probe and the OpenAPI document.
    """
    app = FastAPI(
        title=SERVICE_NAME,
        version=__version__,
        description=API_DESCRIPTION,
        docs_url="/docs",
        openapi_url="/openapi.json",
        license_info={"name": "MIT", "identifier": "MIT"},
    )
    app.include_router(router)
    return app


app = create_app()
"""ASGI entrypoint consumed by uvicorn."""
