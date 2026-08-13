"""The failures the runtime surface is allowed to report, and their shape.

One envelope for every failure — ``{"error", "error_type", "request_id"}`` — because a
caller that has to parse two shapes will parse one of them wrongly. ``error_type`` is a
slug from a closed set, taken from the portfolio-wide failure taxonomy rather than
invented here, so an operator reading a log from another project in the series reads the
same words.

The rule the whole module exists to hold: **an error message is a sentence, not a
diagnostic dump.** It never carries a traceback, the value of a configuration variable,
a raw provider payload, or the caller's own input echoed back. Each of those is a real
leak and not a hypothetical one:

* a traceback is a map of the installed dependency tree;
* a configuration value is a credential whenever the URL carries one;
* a provider payload is another service's internals published through this one;
* echoed input is the field most likely to be enormous, or to contain the thing the
  caller should not see repeated back to them.

Every failure this service raises deliberately therefore carries a message written by
this service. Details worth keeping are logged server-side, where they belong.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from http import HTTPStatus
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field

MAX_REPORTED_FIELDS: Final = 5
"""Validation problems named in one message before the rest are counted."""

MAX_MESSAGE_CHARS: Final = 200
"""Longest single validator message repeated, before it is cut."""

MAX_LOCATION_CHARS: Final = 64
"""Longest field-name segment repeated. A caller controls these, so they are bounded."""

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
"""Control characters, including the newline that would forge a second log line."""


class ErrorType(StrEnum):
    """The stable slugs this service is allowed to answer with.

    Closed on purpose: a caller branches on these, and a slug invented at a call site is
    a slug nobody can branch on until they have seen it in production.
    """

    VALIDATION_ERROR = "validation_error"
    CAPABILITY_MISSING = "capability_missing"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    INTERNAL_ERROR = "internal_error"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    HTTP_ERROR = "http_error"


class ErrorResponse(BaseModel):
    """The one shape every failure is reported in.

    Frozen, and identical across HTTP and the CLI: the CLI prints this object verbatim
    when a run cannot be produced, so a script that reads one reads the other.
    """

    model_config = ConfigDict(frozen=True)

    error: str = Field(description="What went wrong, in one sentence written by this service.")
    error_type: ErrorType = Field(description="Stable slug a caller may branch on.")
    request_id: str | None = Field(
        default=None,
        description="Correlation id of the request that failed, when one was established.",
    )


class RuntimeSurfaceError(RuntimeError):
    """A failure this service reports deliberately.

    Carrying the HTTP status on the exception rather than mapping it at the route keeps
    one place to read what a failure means. Anything not derived from this class is a
    defect in this service, is reported as :data:`ErrorType.INTERNAL_ERROR`, and is
    never reported as a provider failure — a bug that claims a backend failed sends
    whoever is on call to read the wrong service's logs.
    """

    error_type: ClassVar[ErrorType] = ErrorType.INTERNAL_ERROR
    http_status: ClassVar[HTTPStatus] = HTTPStatus.INTERNAL_SERVER_ERROR

    def as_response(self, request_id: str | None) -> ErrorResponse:
        """Return this failure as the envelope, correlated to ``request_id``."""
        return ErrorResponse(
            error=str(self),
            error_type=self.error_type,
            request_id=request_id,
        )


class RequestInvalid(RuntimeSurfaceError):
    """The request was rejected before a run started.

    Raised on the CLI path, where argument parsing produces the same rejection the HTTP
    route's body validation produces. Both end in the same slug, so "the request was
    wrong" reads identically whichever way it arrived.
    """

    error_type: ClassVar[ErrorType] = ErrorType.VALIDATION_ERROR
    http_status: ClassVar[HTTPStatus] = HTTPStatus.UNPROCESSABLE_ENTITY


class CapabilityMissing(RuntimeSurfaceError):
    """The caller asked for something this deployment is not configured to serve.

    Distinct from :class:`BackendUnavailable`, and the distinction is the one an
    operator acts on: this means the deployment was never configured for what was asked
    and retrying changes nothing, while an unavailable backend was configured and failed
    the call. Collapsing them would delete the only signal separating "fix the
    deployment" from "go and look at the other service".
    """

    error_type: ClassVar[ErrorType] = ErrorType.CAPABILITY_MISSING
    http_status: ClassVar[HTTPStatus] = HTTPStatus.SERVICE_UNAVAILABLE


class BackendUnavailable(RuntimeSurfaceError):
    """A configured backend could not serve the call."""

    error_type: ClassVar[ErrorType] = ErrorType.BACKEND_UNAVAILABLE
    http_status: ClassVar[HTTPStatus] = HTTPStatus.SERVICE_UNAVAILABLE


class RunNotReportable(RuntimeSurfaceError):
    """A run came back in a state this service cannot report.

    A defect in this service or in whatever it was given as a runner — a run that never
    reached a terminal status, or one with no report. It keeps the default
    :data:`ErrorType.INTERNAL_ERROR` on purpose: reporting a bug here as a backend
    failure would send whoever is on call to read another service's logs.
    """


def _clean(fragment: str, *, limit: int) -> str:
    """Return ``fragment`` without control characters, cut to ``limit``."""
    collapsed = " ".join(_CONTROL.sub(" ", fragment).split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit]}..."


def _location(raw: object) -> str:
    """Return the dotted field path of one validation error, without its body prefix."""
    if not isinstance(raw, tuple | list):
        return ""
    segments = [str(part) for part in raw]
    if segments and segments[0] == "body":
        segments = segments[1:]
    return ".".join(_clean(segment, limit=MAX_LOCATION_CHARS) for segment in segments)


def describe_validation_errors(errors: Sequence[Mapping[str, object]]) -> str:
    """Return one sentence naming what a validator rejected, and nothing more.

    Built from the field location and the validator's own message. The rejected
    *value* is never included: pydantic reports it in ``input``, and repeating it back
    would echo whatever the caller sent — which is unbounded in size and is the part of
    a request least safe to reproduce.

    Args:
        errors: The mappings a pydantic or FastAPI validation error carries, each with
            a ``loc`` and a ``msg``.

    Returns:
        A single sentence naming at most :data:`MAX_REPORTED_FIELDS` problems, with any
        remainder counted rather than listed.
    """
    reported: list[str] = []
    for error in list(errors)[:MAX_REPORTED_FIELDS]:
        message = _clean(str(error.get("msg", "is invalid")), limit=MAX_MESSAGE_CHARS)
        location = _location(error.get("loc"))
        reported.append(f"{location}: {message}" if location else message)

    remaining = len(errors) - len(reported)
    if remaining > 0:
        reported.append(f"and {remaining} more problem(s)")
    if not reported:
        return "the request could not be validated"
    return "the request is not valid: " + "; ".join(reported)
