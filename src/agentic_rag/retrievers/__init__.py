"""Retrieval backends and the evidence they return.

The retrieve tool in :mod:`agentic_rag.tools.retrieve` is the loop-facing
surface; this package is the outbound one. It holds the evidence value type, the
validated address type, the pinned production-rag contract, and the HTTP adapter
that speaks it.

The in-process :class:`~agentic_rag.tools.retrieve.FakeRetrievalBackend` stays
beside the tool: it is a committed fixture with no outbound surface, so moving it
here would buy symmetry and nothing else.
"""

from __future__ import annotations

from agentic_rag.retrievers.http_p1 import (
    BACKEND_NAME,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
    MAX_RESPONSE_BYTES,
    HttpRetrievalBackend,
    RemoteQueryOutcome,
)
from agentic_rag.retrievers.p1_contract import (
    P1_COMMIT,
    P1_REPOSITORY,
    P1_TAG,
    REFUSAL_REASONS,
    REQUEST_ID_HEADER,
    EvidenceState,
    P1Citation,
    P1QueryRequest,
    P1QueryResponse,
    query_path,
    verify_contract,
)
from agentic_rag.retrievers.passage import Passage
from agentic_rag.retrievers.service_url import InvalidServiceUrlError, ServiceUrl

__all__ = [
    "BACKEND_NAME",
    "DEFAULT_CONNECT_TIMEOUT",
    "DEFAULT_READ_TIMEOUT",
    "MAX_RESPONSE_BYTES",
    "P1_COMMIT",
    "P1_REPOSITORY",
    "P1_TAG",
    "REFUSAL_REASONS",
    "REQUEST_ID_HEADER",
    "EvidenceState",
    "HttpRetrievalBackend",
    "InvalidServiceUrlError",
    "P1Citation",
    "P1QueryRequest",
    "P1QueryResponse",
    "Passage",
    "RemoteQueryOutcome",
    "ServiceUrl",
    "query_path",
    "verify_contract",
]
