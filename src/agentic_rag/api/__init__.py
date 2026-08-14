"""The runtime surface: the contract, the errors, and the service both callers use.

``POST /v1/research`` and ``python -m agentic_rag.research`` are two doors into one
room. What they share lives here — the request and response models, the error envelope,
the correlation id, and :class:`~agentic_rag.api.service.ResearchService`, which is the
only thing in this package that turns a request into a run.

The agent loop itself is not re-exported here. It is ``agentic_rag.agent``, and a
runtime surface that re-exported it would invite a caller to import the reasoning
through the transport.
"""

from __future__ import annotations

from agentic_rag.api.errors import (
    BackendUnavailable,
    CapabilityMissing,
    ErrorResponse,
    ErrorType,
    RequestInvalid,
    RunNotReportable,
    RuntimeSurfaceError,
    describe_validation_errors,
)
from agentic_rag.api.request_id import (
    MAX_REQUEST_ID_CHARS,
    REQUEST_ID_HEADER,
    is_safe_request_id,
    new_request_id,
    resolve_request_id,
)
from agentic_rag.api.schemas import (
    MAX_MAX_STEPS,
    MAX_QUESTION_CHARS,
    MAX_TOP_K,
    MIN_MAX_STEPS,
    MIN_TOP_K,
    ResearchRequest,
    ResearchResponse,
    RetrieverChoice,
)
from agentic_rag.api.service import (
    ResearchRunner,
    ResearchService,
    RetrieverFactory,
    build_retriever,
    render_response,
)

__all__ = [
    "MAX_MAX_STEPS",
    "MAX_QUESTION_CHARS",
    "MAX_REQUEST_ID_CHARS",
    "MAX_TOP_K",
    "MIN_MAX_STEPS",
    "MIN_TOP_K",
    "REQUEST_ID_HEADER",
    "BackendUnavailable",
    "CapabilityMissing",
    "ErrorResponse",
    "ErrorType",
    "RequestInvalid",
    "ResearchRequest",
    "ResearchResponse",
    "ResearchRunner",
    "ResearchService",
    "RetrieverChoice",
    "RetrieverFactory",
    "RunNotReportable",
    "RuntimeSurfaceError",
    "build_retriever",
    "describe_validation_errors",
    "is_safe_request_id",
    "new_request_id",
    "render_response",
    "resolve_request_id",
]
