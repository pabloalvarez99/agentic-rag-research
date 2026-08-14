"""Vercel zero-config FastAPI entry (repo root).

The deployed instance sets no ``PRODUCTION_RAG_URL``, so every request it serves runs
the agent loop over the in-process fixture retriever. That is the point of the hosted
copy: the loop's control flow, budget accounting, trace and refusal path are exercisable
from a browser with no credential and no clone. It supports no claim about retrieval or
answer quality.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Imported after the path edit above, which is the whole reason this shim exists: the
# platform runs this file from the repository root, where ``src`` is not yet importable.
from agentic_rag.main import app  # noqa: E402

__all__ = ["app"]
