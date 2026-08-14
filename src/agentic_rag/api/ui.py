"""Server-rendered free-path research demo over the existing research service."""

from __future__ import annotations

import logging
from http import HTTPStatus
from pathlib import Path
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from agentic_rag.api.errors import (
    ErrorResponse,
    ErrorType,
    RequestInvalid,
    RuntimeSurfaceError,
    describe_validation_errors,
)
from agentic_rag.api.handlers import correlation_id
from agentic_rag.api.routes import get_service
from agentic_rag.api.schemas import MAX_MAX_STEPS, MIN_MAX_STEPS, ResearchRequest
from agentic_rag.api.service import ResearchService

PACKAGE_DIRECTORY: Final = Path(__file__).resolve().parent.parent
TEMPLATE_DIRECTORY: Final = PACKAGE_DIRECTORY / "templates"
STATIC_DIRECTORY: Final = PACKAGE_DIRECTORY / "static"
DEMO_QUESTION: Final = "Why do bounded research agents need explicit stop reasons?"

LOGGER: Final = logging.getLogger(__name__)
templates = Jinja2Templates(directory=TEMPLATE_DIRECTORY)
router = APIRouter(include_in_schema=False)


def _page_context(request: Request, **extra: object) -> dict[str, object]:
    """Return the shared template context for one page render."""
    return {
        "request": request,
        "demo_question": DEMO_QUESTION,
        "min_max_steps": MIN_MAX_STEPS,
        "max_max_steps": MAX_MAX_STEPS,
        **extra,
    }


def _render_failure(
    request: Request,
    failure: RuntimeSurfaceError,
    *,
    question: str,
    max_steps: str,
) -> Response:
    """Render one typed failure without exposing diagnostics or configuration values."""
    request_id = correlation_id(request)
    error = failure.as_response(request_id)
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context=_page_context(
            request,
            error=error,
            question=question,
            selected_max_steps=max_steps,
        ),
        status_code=int(failure.http_status),
    )


@router.get("/", response_class=HTMLResponse, summary="Free deterministic research demo")
def research_home(request: Request) -> Response:
    """Render the research form with no provider or network dependency."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=_page_context(request, question=DEMO_QUESTION, selected_max_steps="4"),
    )


@router.post("/ui/research", response_class=HTMLResponse)
def research_ui(
    request: Request,
    question: Annotated[str, Form()],
    max_steps: Annotated[str, Form()],
    service: Annotated[ResearchService, Depends(get_service)],
) -> Response:
    """Run the free backend and render its report, citations, status, and trace."""
    request_id = correlation_id(request)
    try:
        payload = ResearchRequest.model_validate(
            {"question": question, "max_steps": max_steps, "retriever": "fake"}
        )
        result = service.run(payload, request_id=request_id)
    except ValidationError as error:
        failure = RequestInvalid(describe_validation_errors(error.errors()))
        return _render_failure(request, failure, question=question, max_steps=max_steps)
    except RuntimeSurfaceError as failure:
        return _render_failure(request, failure, question=question, max_steps=max_steps)
    except Exception as error:  # pragma: no cover - defensive browser contract
        LOGGER.exception("UI research failed request_id=%s", request_id, exc_info=error)
        envelope = ErrorResponse(
            error="the service failed to complete the request",
            error_type=ErrorType.INTERNAL_ERROR,
            request_id=request_id,
        )
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context=_page_context(
                request,
                error=envelope,
                question=question,
                selected_max_steps=max_steps,
            ),
            status_code=int(HTTPStatus.INTERNAL_SERVER_ERROR),
        )

    return templates.TemplateResponse(
        request=request,
        name="result.html",
        context=_page_context(
            request,
            result=result,
            question=question,
            selected_max_steps=max_steps,
        ),
    )
