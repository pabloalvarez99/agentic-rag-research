"""Turning every failure into the one envelope, with nothing extra attached.

Four handlers cover everything that can go wrong between a socket and a run: a failure
this service raised deliberately, a body the contract rejects, a routing error, and a
defect. All four answer in :class:`~agentic_rag.api.errors.ErrorResponse` and all four
carry the request's correlation id, in the body and in the header.

The last one is the reason this module exists. Without a catch-all, an unexpected
exception leaves Starlette's default 500 — a plain-text body in a different shape, with
no correlation id, and, depending on how the server is configured, a traceback. A client
would have to parse two error formats and would learn nothing it could report back.

What the handlers deliberately do not do is decide what a failure *means*. The status
code and the slug travel on the exception class, so there is one place to read the
mapping rather than one per route.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agentic_rag.api.errors import (
    ErrorResponse,
    ErrorType,
    RuntimeSurfaceError,
    describe_validation_errors,
)
from agentic_rag.api.middleware import request_id_of
from agentic_rag.api.request_id import REQUEST_ID_HEADER, resolve_request_id

LOGGER: Final = logging.getLogger(__name__)

_ROUTING_SLUGS: Final[dict[int, ErrorType]] = {
    HTTPStatus.NOT_FOUND: ErrorType.NOT_FOUND,
    HTTPStatus.METHOD_NOT_ALLOWED: ErrorType.METHOD_NOT_ALLOWED,
}
"""Routing failures worth a slug of their own; everything else is a generic HTTP error."""


def correlation_id(request: Request) -> str:
    """Return the id established for ``request``, resolving one if nothing did.

    The fallback matters for a failure raised outside the middleware, where no id was
    ever promised in a response header — minting one there is safe, and answering
    without one would leave the caller nothing to quote in a bug report.
    """
    established = request_id_of(request.scope)
    if established is not None:
        return established
    return resolve_request_id(request.headers.get(REQUEST_ID_HEADER))


def error_response(
    request: Request,
    *,
    status: int,
    error: str,
    error_type: ErrorType,
) -> JSONResponse:
    """Return one failure as the shared envelope, correlated and headed."""
    request_id = correlation_id(request)
    body = ErrorResponse(error=error, error_type=error_type, request_id=request_id)
    return JSONResponse(
        status_code=status,
        content=body.model_dump(mode="json"),
        headers={REQUEST_ID_HEADER: request_id},
    )


async def handle_runtime_surface_error(request: Request, exc: Exception) -> JSONResponse:
    """Answer a failure this service raised on purpose.

    Its message was written to be read by a caller: it names the capability that is
    missing or the backend that failed, and never the configuration value behind
    either.
    """
    failure = exc if isinstance(exc, RuntimeSurfaceError) else RuntimeSurfaceError(str(exc))
    if failure.error_type is ErrorType.INTERNAL_ERROR:
        # A defect: the stack is the only thing that will diagnose it, so it is logged.
        LOGGER.error("request failed request_id=%s", correlation_id(request), exc_info=failure)
    else:
        # An expected operational outcome — an unconfigured capability, a backend that
        # is down. A traceback here would train an operator to skim stack traces.
        LOGGER.warning(
            "request refused type=%s request_id=%s",
            failure.error_type.value,
            correlation_id(request),
        )
    return error_response(
        request,
        status=int(failure.http_status),
        error=str(failure),
        error_type=failure.error_type,
    )


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Answer a body the contract rejects.

    The message names the offending fields and the validator's complaint about each.
    It never quotes the value: that is the part of a request least safe to reproduce and
    the part most likely to be enormous.
    """
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    return error_response(
        request,
        status=int(HTTPStatus.UNPROCESSABLE_ENTITY),
        error=describe_validation_errors(errors),
        error_type=ErrorType.VALIDATION_ERROR,
    )


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """Answer a routing failure in the same shape a research failure uses.

    An unknown path answering in a different shape than a known one makes a client
    write two parsers, and the one it writes for the rare case is the one that is
    wrong.
    """
    status = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    detail = exc.detail if isinstance(exc, StarletteHTTPException) else "request failed"
    return error_response(
        request,
        status=status,
        error=str(detail),
        error_type=_ROUTING_SLUGS.get(status, ErrorType.HTTP_ERROR),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Answer a defect in this service without describing it to the caller.

    The stack goes to the log, where an operator can read it; the caller gets one
    sentence and the correlation id that ties it to that log line. A traceback in a
    response body is a map of the installed dependency tree, and it is published to
    whoever asked — including whoever caused the exception on purpose.
    """
    LOGGER.exception("unhandled error request_id=%s", correlation_id(request), exc_info=exc)
    return error_response(
        request,
        status=int(HTTPStatus.INTERNAL_SERVER_ERROR),
        error="the service failed to complete the request",
        error_type=ErrorType.INTERNAL_ERROR,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register every handler on ``app``.

    Args:
        app: The application whose failures are to answer in the shared envelope.
    """
    app.add_exception_handler(RuntimeSurfaceError, handle_runtime_surface_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
