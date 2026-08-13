"""The shipped dataset, checked as a dataset rather than as an input.

Two different things are asserted here and they should not be confused:

* the file satisfies its own integrity rules, and covers what it claims to cover;
* every expectation in it follows from a documented rule, checked against the
  independent model in ``spec_model.py``.

The second is the leakage check. A case whose expectation was copied from an
implementation's output survives the first and fails the second — unless the
implementation happens to agree with its own documentation, which is the
condition being verified rather than assumed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from spec_model import predict

from agentic_rag.evals.dataset import (
    CASE_CATEGORIES,
    DATASET_SCHEMA_VERSION,
    EvalCase,
    EvalDataset,
    load_dataset,
)
from agentic_rag.tools.retrieve import DEFAULT_CORPUS

DATASET_PATH = Path("data/eval/golden_research.jsonl")
MINIMUM_CASES = 48


@pytest.fixture(scope="module")
def dataset() -> EvalDataset:
    return load_dataset(DATASET_PATH, minimum_cases=MINIMUM_CASES)


def test_the_shipped_dataset_validates(dataset: EvalDataset) -> None:
    assert dataset.case_count >= MINIMUM_CASES
    assert dataset.sha256.startswith("sha256:")


def test_every_slice_is_covered(dataset: EvalDataset) -> None:
    counts = dataset.counts_by_category()
    assert set(counts) == set(CASE_CATEGORIES)
    empty = [category for category, count in counts.items() if count == 0]
    assert not empty, f"slices with no cases: {empty}"


def test_cases_are_semantically_distinct(dataset: EvalDataset) -> None:
    """Distinct questions, and distinct meanings except where a group says otherwise."""
    assert len({case.id for case in dataset}) == dataset.case_count
    assert len({case.question for case in dataset}) == dataset.case_count

    normalized: dict[str, list[EvalCase]] = {}
    for case in dataset:
        normalized.setdefault(case.normalized_question, []).append(case)
    for text, members in normalized.items():
        if len(members) == 1:
            continue
        groups = {case.normalization_group for case in members}
        assert groups != {None}, f"{text!r} is repeated outside a normalization group"
        assert len(groups) == 1, f"{text!r} spans several normalization groups"


def test_every_case_carries_its_derivation(dataset: EvalDataset) -> None:
    for case in dataset:
        assert len(case.rationale) >= 20, case.id
        assert case.rationale == case.rationale.strip()


def test_schema_version_is_uniform(dataset: EvalDataset) -> None:
    for case in dataset:
        assert case.schema_version == DATASET_SCHEMA_VERSION, case.id


def test_declared_provenance_exists_in_the_corpus(dataset: EvalDataset) -> None:
    chunks = {document.chunk_id for document in DEFAULT_CORPUS}
    sources = {document.source_path for document in DEFAULT_CORPUS}
    for case in dataset:
        assert set(case.expected_chunk_ids) <= chunks, case.id
        assert set(case.expected_source_paths) <= sources, case.id


def test_no_case_can_carry_an_answer() -> None:
    """The schema forbids what a leaked expectation would need to be written in."""
    fields = set(EvalCase.model_fields)
    forbidden = {"report", "answer", "expected_report", "expected_answer", "snippet", "text"}
    assert fields & forbidden == set()
    assert EvalCase.model_config["extra"] == "forbid"


def test_every_expectation_is_derivable_from_the_documented_rules(
    dataset: EvalDataset,
) -> None:
    """No case may expect something the documented rules do not imply.

    This is the check that a curated expectation is a derivation rather than a
    recording. It runs against ``spec_model``, which never imports the agent.
    """
    problems: list[str] = []
    for case in dataset:
        expected = predict(case.question, max_steps=case.max_steps, top_k=case.top_k)
        if expected.status != case.expected_terminal_status:
            problems.append(
                f"{case.id}: expects status {case.expected_terminal_status!r}, "
                f"rules give {expected.status!r}"
            )
        if expected.stop_reason != case.expected_stop_reason:
            problems.append(
                f"{case.id}: expects reason {case.expected_stop_reason!r}, "
                f"rules give {expected.stop_reason!r}"
            )
        if len(expected.plan) < case.expected_min_plan_size:
            problems.append(
                f"{case.id}: expects a plan of at least {case.expected_min_plan_size}, "
                f"rules give {len(expected.plan)}"
            )
        if not set(case.expected_chunk_ids) <= set(expected.evidence_ids):
            problems.append(
                f"{case.id}: expects chunks {list(case.expected_chunk_ids)}, "
                f"rules give {list(expected.evidence_ids)}"
            )
        if not set(case.expected_source_paths) <= set(expected.source_paths):
            problems.append(
                f"{case.id}: expects sources {list(case.expected_source_paths)}, "
                f"rules give {list(expected.source_paths)}"
            )
        held = len(expected.evidence_ids)
        if held < case.expected_min_citations:
            problems.append(
                f"{case.id}: expects at least {case.expected_min_citations} citations, "
                f"rules leave {held} passages to cite"
            )
        if case.expected_max_citations is not None and held > case.expected_max_citations:
            problems.append(
                f"{case.id}: expects at most {case.expected_max_citations} citations, "
                f"rules leave {held} passages to cite"
            )
    assert not problems, "\n".join(problems)


def test_normalization_groups_are_pairs_that_could_disagree(dataset: EvalDataset) -> None:
    groups: dict[str, list[EvalCase]] = {}
    for case in dataset:
        if case.normalization_group is not None:
            groups.setdefault(case.normalization_group, []).append(case)
    assert groups, "the normalization slice needs at least one group"
    for name, members in groups.items():
        assert len(members) >= 2, f"group {name!r} cannot prove invariance alone"
        assert len({case.question for case in members}) == len(members), name
        assert len({case.normalized_question for case in members}) >= 1, name
        outcomes = {(case.expected_terminal_status, case.expected_stop_reason) for case in members}
        assert len(outcomes) == 1, f"group {name!r} expects different outcomes: {outcomes}"


def test_the_refusal_slice_covers_both_ways_of_refusing(dataset: EvalDataset) -> None:
    """A shortage of evidence and a shortage of budget must not be conflated."""
    reasons = {
        case.expected_stop_reason
        for case in dataset
        if case.category == "no_evidence_refusal"
    }
    assert reasons == {"no_evidence", "insufficient_evidence"}


def test_the_budget_slice_leaves_evidence_on_the_table(dataset: EvalDataset) -> None:
    budget_cases = [case for case in dataset if case.category == "budget_pressure_partial"]
    assert budget_cases
    for case in budget_cases:
        assert case.expected_terminal_status == "budget_exhausted", case.id
        assert case.expected_min_citations >= 1, case.id
