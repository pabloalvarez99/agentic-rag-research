"""The request contract: what it accepts, what it refuses, and what it may not drift from.

The bound tests are the important ones. The API restates limits that ``ResearchState``
and ``RetrieveRequest`` already enforce, so a caller gets a readable rejection at the
edge instead of a failure deep inside a run — and a restated limit is a limit that can
be changed in one place and not the other. These assertions compare the two directly.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from agentic_rag.agent.state import DEFAULT_MAX_STEPS, ResearchState
from agentic_rag.api.schemas import (
    MAX_MAX_STEPS,
    MAX_QUESTION_CHARS,
    MAX_TOP_K,
    MIN_MAX_STEPS,
    MIN_TOP_K,
    ResearchRequest,
    RetrieverChoice,
)
from agentic_rag.tools.retrieve import DEFAULT_TOP_K, RetrieveRequest

ANSWERABLE = "What does hybrid retrieval buy over dense retrieval alone?"


def properties(model: type[BaseModel]) -> dict[str, Any]:
    schema: dict[str, Any] = model.model_json_schema()["properties"]
    return schema


def test_the_defaults_are_the_free_path() -> None:
    request = ResearchRequest(question=ANSWERABLE)

    assert request.max_steps == DEFAULT_MAX_STEPS
    assert request.top_k == DEFAULT_TOP_K
    assert request.retriever is RetrieverChoice.FAKE


def test_a_question_is_trimmed_before_it_is_validated() -> None:
    assert ResearchRequest(question=f"  {ANSWERABLE}\n").question == ANSWERABLE


@pytest.mark.parametrize("blank", ["", " ", "\t\n  ", " "])
def test_a_blank_question_is_refused(blank: str) -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(question=blank)


def test_an_oversized_question_is_refused_one_character_past_the_bound() -> None:
    assert ResearchRequest(question="q" * MAX_QUESTION_CHARS).question

    with pytest.raises(ValidationError):
        ResearchRequest(question="q" * (MAX_QUESTION_CHARS + 1))


@pytest.mark.parametrize("max_steps", [MIN_MAX_STEPS, MAX_MAX_STEPS])
def test_the_step_budget_accepts_both_boundaries(max_steps: int) -> None:
    assert ResearchRequest(question=ANSWERABLE, max_steps=max_steps).max_steps == max_steps


@pytest.mark.parametrize("max_steps", [MIN_MAX_STEPS - 1, MAX_MAX_STEPS + 1, -1])
def test_the_step_budget_refuses_what_is_outside_it(max_steps: int) -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(question=ANSWERABLE, max_steps=max_steps)


@pytest.mark.parametrize("top_k", [MIN_TOP_K, MAX_TOP_K])
def test_the_evidence_budget_accepts_both_boundaries(top_k: int) -> None:
    assert ResearchRequest(question=ANSWERABLE, top_k=top_k).top_k == top_k


@pytest.mark.parametrize("top_k", [MIN_TOP_K - 1, MAX_TOP_K + 1])
def test_the_evidence_budget_refuses_what_is_outside_it(top_k: int) -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(question=ANSWERABLE, top_k=top_k)


def test_an_unknown_field_is_refused_rather_than_ignored() -> None:
    with pytest.raises(ValidationError) as rejected:
        ResearchRequest.model_validate({"question": ANSWERABLE, "max_step": 3})

    assert rejected.value.errors()[0]["type"] == "extra_forbidden"


def test_an_unknown_retriever_is_refused() -> None:
    with pytest.raises(ValidationError):
        ResearchRequest.model_validate({"question": ANSWERABLE, "retriever": "openai"})


def test_the_retriever_set_is_exactly_the_two_implemented_backends() -> None:
    assert [choice.value for choice in RetrieverChoice] == ["fake", "http"]


def test_the_step_budget_bound_is_the_one_the_state_enforces() -> None:
    api = properties(ResearchRequest)["max_steps"]
    canonical = properties(ResearchState)["max_steps"]

    assert (api["minimum"], api["maximum"]) == (canonical["minimum"], canonical["maximum"])


def test_the_evidence_budget_bound_is_the_one_the_retrieve_tool_enforces() -> None:
    api = properties(ResearchRequest)["top_k"]
    canonical = properties(RetrieveRequest)["top_k"]

    assert (api["minimum"], api["maximum"]) == (canonical["minimum"], canonical["maximum"])


def test_the_question_bound_is_the_one_the_retrieve_tool_enforces() -> None:
    api = properties(ResearchRequest)["question"]
    canonical = properties(RetrieveRequest)["question"]

    assert api["maxLength"] == canonical["maxLength"]
    assert api["minLength"] == canonical["minLength"]
