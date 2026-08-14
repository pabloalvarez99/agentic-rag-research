"""Tools the agent loop can call.

M1 ships one: ``retrieve``, and the retrieval boundary behind it. The protocol it
satisfies lives in :mod:`agentic_rag.tools.base`, and ``plan`` and ``critique``
will satisfy the same one.
"""

from __future__ import annotations

from agentic_rag.corpus import Document
from agentic_rag.tools.base import Tool, ToolError
from agentic_rag.tools.retrieve import (
    DEFAULT_CORPUS,
    DEFAULT_TOP_K,
    PRODUCTION_RAG_URL_ENV,
    FakeRetrievalBackend,
    HttpRetrievalBackend,
    Passage,
    RetrievalBackend,
    RetrieveRequest,
    RetrieveResult,
    RetrieveTool,
    build_retrieve_tool,
)

__all__ = [
    "DEFAULT_CORPUS",
    "DEFAULT_TOP_K",
    "PRODUCTION_RAG_URL_ENV",
    "Document",
    "FakeRetrievalBackend",
    "HttpRetrievalBackend",
    "Passage",
    "RetrievalBackend",
    "RetrieveRequest",
    "RetrieveResult",
    "RetrieveTool",
    "Tool",
    "ToolError",
    "build_retrieve_tool",
]
