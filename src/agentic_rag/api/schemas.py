"""What a caller may ask for, and what comes back.

These models are the public contract of the runtime surface, and they are deliberately
thin: the response is assembled from the *canonical* models — ``ResearchStatus``,
``Citation``, ``TraceEvent`` — rather than from transport-local copies of them. A second
citation model would be a second place for the citation shape to change, and the two
would disagree on the day one of them was updated.

The request is strict in three ways, each of which is a failure mode this project has
already reasoned about somewhere else:

* **Unknown fields are rejected.** A misspelled ``max_step`` that silently falls back to
  the default produces a run that looks fine and answers under a budget nobody asked
  for. ``RetrieveRequest`` forbids extras for the same reason.
* **Bounds are the domain's bounds.** ``max_steps`` is bounded by ``ResearchState`` and
  ``top_k`` by ``RetrieveRequest``; this module restates them so a bad request fails at
  the edge with a readable message rather than deep inside a run. A test asserts the two
  sets of numbers are equal, so the restatement cannot drift.
* **The retriever is named explicitly and defaults to the free one.** Selecting a
  backend is the caller's decision, made in the request — not one the server infers from
  its environment behind the caller's back.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.agent.state import DEFAULT_MAX_STEPS, ResearchStatus, TraceEvent
from agentic_rag.agent.synthesizer import Citation
from agentic_rag.tools.retrieve import DEFAULT_TOP_K

MIN_MAX_STEPS: Final = 1
"""Fewest steps a run may be given: one retrieval, then answer or refuse."""

MAX_MAX_STEPS: Final = 20
"""Most steps a run may be given, matching the bound ``ResearchState`` enforces."""

MIN_TOP_K: Final = 1
"""Fewest passages one retrieval step may return."""

MAX_TOP_K: Final = 50
"""Most passages one retrieval step may return, matching ``RetrieveRequest``."""

MAX_QUESTION_CHARS: Final = 8_000
"""Longest question accepted, matching the bound the retrieve tool already enforces."""


class RetrieverChoice(StrEnum):
    """Which retrieval backend a run is to be served by.

    A closed set rather than a free string: the two values are the two implementations
    of the retrieval seam, and a caller asking for a third has made a mistake worth
    reporting at the edge.
    """

    FAKE = "fake"
    HTTP = "http"


class ResearchRequest(BaseModel):
    """One research run, as a caller asks for it.

    Whitespace is stripped before validation, so a question of three spaces is empty and
    is rejected rather than becoming a run with nothing to research.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "question": "Why use citations in RAG?",
                    "max_steps": 3,
                    "top_k": 5,
                    "retriever": "fake",
                }
            ]
        },
    )

    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_CHARS,
        description="The research question. Trimmed; may not be empty.",
    )
    max_steps: int = Field(
        default=DEFAULT_MAX_STEPS,
        ge=MIN_MAX_STEPS,
        le=MAX_MAX_STEPS,
        description="Hard cap on retrieval steps for this run.",
    )
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        ge=MIN_TOP_K,
        le=MAX_TOP_K,
        description="Upper bound on the passages one retrieval step returns.",
    )
    retriever: RetrieverChoice = Field(
        default=RetrieverChoice.FAKE,
        description=(
            "Retrieval backend to serve the run. 'fake' is deterministic, in-process and "
            "contacts nothing; 'http' requires a configured production-rag instance and "
            "fails with capability_missing when there is none."
        ),
    )


class ResearchResponse(BaseModel):
    """A finished run, as the API and the CLI both report it.

    Exactly the fields the canonical contract names. ``stop_reason`` is not among them
    and is not added here: it is already carried by the terminal ``stop`` event of the
    trace, together with the status, the steps used and the budget, and a seventh
    top-level field would be a contract change this milestone was not asked to make.
    """

    model_config = ConfigDict(frozen=True)

    status: ResearchStatus = Field(description="How the run ended. Always terminal.")
    report: str = Field(description="The composed report, or the refusal and its gaps.")
    citations: list[Citation] = Field(
        default_factory=list,
        description="One entry per marker in the report, in marker order.",
    )
    steps_used: int = Field(ge=0, description="Retrieval steps the run actually spent.")
    trace: list[TraceEvent] = Field(
        default_factory=list,
        description="Every event the run recorded, oldest first, ending in 'stop'.",
    )
    request_id: str = Field(description="Correlation id of this run, echoed in the header.")
