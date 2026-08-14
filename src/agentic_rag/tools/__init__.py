"""Tools the agent loop can call.

M1 ships one: ``retrieve``, and the retrieval boundary behind it. The protocol it
satisfies lives in :mod:`agentic_rag.tools.base`, and ``plan`` and ``critique``
will satisfy the same one.
"""

from __future__ import annotations

from agentic_rag.corpus import Document
from agentic_rag.tools.base import (
    ERROR_BACKEND_UNAVAILABLE,
    ERROR_CONTRACT_MISMATCH,
    ERROR_PROVIDER,
    ERROR_RATE_LIMITED,
    ERROR_TOOL,
    ERROR_UNAUTHORIZED,
    ERROR_VALIDATION,
    Tool,
    ToolError,
)
from agentic_rag.tools.http_p1 import (
    HttpProductionRagClient,
    HttpRetrievalBackend,
    RemoteQueryOutcome,
)
from agentic_rag.tools.lexicon import (
    DEFAULT_LEXICON_LIMIT,
    LexiconEntry,
    LexiconRequest,
    LexiconResult,
    LexiconTool,
)
from agentic_rag.tools.p1_contract import EvidenceState
from agentic_rag.tools.retrieve import (
    DEFAULT_CORPUS,
    DEFAULT_TOP_K,
    PRODUCTION_RAG_URL_ENV,
    FakeRetrievalBackend,
    Passage,
    RetrievalBackend,
    RetrieveRequest,
    RetrieveResult,
    RetrieveTool,
    build_retrieve_tool,
)
from agentic_rag.tools.search_notes import (
    DEFAULT_NOTES_LIMIT,
    SearchNotesRequest,
    SearchNotesResult,
    SearchNotesTool,
)
from agentic_rag.tools.service_url import InvalidServiceUrlError, ServiceUrl

__all__ = [
    "DEFAULT_CORPUS",
    "DEFAULT_TOP_K",
    "DEFAULT_NOTES_LIMIT",
    "DEFAULT_LEXICON_LIMIT",
    "ERROR_BACKEND_UNAVAILABLE",
    "ERROR_CONTRACT_MISMATCH",
    "ERROR_PROVIDER",
    "ERROR_RATE_LIMITED",
    "ERROR_TOOL",
    "ERROR_UNAUTHORIZED",
    "ERROR_VALIDATION",
    "PRODUCTION_RAG_URL_ENV",
    "Document",
    "EvidenceState",
    "FakeRetrievalBackend",
    "HttpProductionRagClient",
    "HttpRetrievalBackend",
    "InvalidServiceUrlError",
    "Passage",
    "RemoteQueryOutcome",
    "RetrievalBackend",
    "RetrieveRequest",
    "RetrieveResult",
    "RetrieveTool",
    "ServiceUrl",
    "LexiconEntry",
    "LexiconRequest",
    "LexiconResult",
    "LexiconTool",
    "SearchNotesRequest",
    "SearchNotesResult",
    "SearchNotesTool",
    "Tool",
    "ToolError",
    "build_retrieve_tool",
]
