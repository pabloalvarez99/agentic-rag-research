"""The validator must reject every shape it claims to reject.

A validator nobody has broken on purpose is a validator nobody knows the strength
of. Each test below builds one specific defect and asserts the specific error code
it should produce, so a rule that quietly stops firing fails here rather than
letting a bad dataset through unnoticed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agentic_rag.evals.dataset import (
    DATASET_SCHEMA_VERSION,
    DatasetInvalid,
    EvalCase,
    file_digest,
    load_dataset,
    read_cases,
    validate_dataset,
)

MINIMUM = 1


def case_payload(**overrides: Any) -> dict[str, Any]:
    """Return a valid case payload with the given fields replaced."""
    payload: dict[str, Any] = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "id": "reference-case",
        "category": "single_source_answerable",
        "question": "What is reciprocal rank fusion?",
        "max_steps": 4,
        "top_k": 5,
        "expected_terminal_status": "done",
        "expected_stop_reason": "evidence_sufficient",
        "expected_min_citations": 1,
        "expected_max_citations": 1,
        "expected_source_paths": ["docs/retrieval.md"],
        "expected_chunk_ids": ["hybrid-retrieval-1"],
        "expected_min_plan_size": 1,
        "expects_repeated_evidence": False,
        "normalization_group": None,
        "rationale": "Only the hybrid passage carries these terms, so one step answers it.",
    }
    payload.update(overrides)
    return payload


def build_case(**overrides: Any) -> EvalCase:
    return EvalCase.model_validate(case_payload(**overrides))


def codes(cases: tuple[EvalCase, ...]) -> set[str]:
    return {
        error.code
        for error in validate_dataset(cases, minimum_cases=MINIMUM, required_categories=())
    }


def test_the_reference_case_is_valid() -> None:
    assert codes((build_case(),)) == set()


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        EvalCase.model_validate(case_payload(expected_report="a passage [1]"))


def test_a_wrong_schema_version_is_rejected() -> None:
    assert "unsupported_schema_version" in codes((build_case(schema_version="0.9.0"),))


def test_a_non_kebab_id_is_rejected() -> None:
    assert "malformed_id" in codes((build_case(id="Reference_Case"),))


def test_duplicate_ids_are_rejected() -> None:
    duplicate = (build_case(), build_case(question="Explain reranking."))
    assert "duplicate_id" in codes(duplicate)


def test_duplicate_questions_are_rejected() -> None:
    duplicate = (build_case(), build_case(id="second-case"))
    assert "duplicate_question" in codes(duplicate)


def test_questions_differing_only_in_surface_form_need_a_group() -> None:
    pair = (
        build_case(),
        build_case(id="second-case", question="what   is RECIPROCAL rank fusion?"),
    )
    assert "duplicate_normalized_question" in codes(pair)


def test_a_surface_form_group_permits_the_pair() -> None:
    pair = (
        build_case(normalization_group="fusion"),
        build_case(
            id="second-case",
            question="WHAT IS RECIPROCAL RANK FUSION?",
            normalization_group="fusion",
        ),
    )
    assert codes(pair) == set()


def test_an_impossible_status_and_reason_pair_is_rejected() -> None:
    broken = build_case(expected_terminal_status="done", expected_stop_reason="no_evidence")
    assert "impossible_outcome" in codes((broken,))


def test_inverted_citation_bounds_are_rejected() -> None:
    broken = build_case(expected_min_citations=3, expected_max_citations=1)
    assert "inverted_citation_bounds" in codes((broken,))


def test_a_citation_floor_no_run_could_reach_is_rejected() -> None:
    broken = build_case(
        max_steps=1,
        top_k=1,
        expected_min_citations=5,
        expected_max_citations=None,
    )
    assert "unreachable_citation_floor" in codes((broken,))


def test_a_refusal_with_no_evidence_may_not_expect_citations() -> None:
    broken = build_case(
        id="refusal-with-citations",
        category="no_evidence_refusal",
        question="Who won the 1994 world cup final?",
        expected_terminal_status="refused",
        expected_stop_reason="no_evidence",
        expected_min_citations=1,
    )
    assert "citations_expected_from_no_evidence" in codes((broken,))


def test_a_refusal_with_no_evidence_may_not_expect_provenance() -> None:
    broken = build_case(
        id="refusal-with-provenance",
        category="no_evidence_refusal",
        question="Who won the 1994 world cup final?",
        expected_terminal_status="refused",
        expected_stop_reason="no_evidence",
        expected_min_citations=0,
        expected_max_citations=0,
    )
    assert "provenance_expected_from_no_evidence" in codes((broken,))


def test_repeated_evidence_needs_room_for_two_steps() -> None:
    broken = build_case(max_steps=1, expects_repeated_evidence=True)
    assert "repeat_needs_two_steps" in codes((broken,))


def test_a_short_question_may_not_expect_a_split_plan() -> None:
    broken = build_case(expected_min_plan_size=2)
    assert "plan_size_contradicts_length" in codes((broken,))


def test_a_plan_larger_than_the_budget_is_rejected() -> None:
    broken = build_case(
        question=(
            "How does hybrid retrieval fuse two rankings and how does a cross-encoder "
            "reranker reorder the shortlist?"
        ),
        max_steps=1,
        expected_min_plan_size=2,
    )
    assert "plan_exceeds_budget" in codes((broken,))


def test_provenance_outside_the_corpus_is_rejected() -> None:
    broken = build_case(expected_chunk_ids=["invented-1"])
    assert "unknown_chunk_id" in codes((broken,))


def test_a_source_path_outside_the_corpus_is_rejected() -> None:
    broken = build_case(expected_source_paths=["docs/invented.md"])
    assert "unknown_source_path" in codes((broken,))


def test_a_chunk_and_source_that_disagree_are_rejected() -> None:
    broken = build_case(
        expected_chunk_ids=["hybrid-retrieval-1"],
        expected_source_paths=["docs/ingest.md"],
    )
    assert "provenance_disagrees" in codes((broken,))


def test_a_single_source_case_may_not_name_two_documents() -> None:
    broken = build_case(
        expected_chunk_ids=["hybrid-retrieval-1", "chunking-1"],
        expected_source_paths=["docs/retrieval.md", "docs/ingest.md"],
        expected_max_citations=2,
    )
    assert "slice_mismatch" in codes((broken,))


def test_a_lone_normalization_group_is_rejected() -> None:
    lonely = build_case(category="text_normalization", normalization_group="alone")
    assert "lonely_normalization_group" in codes((lonely,))


def test_a_normalization_group_expecting_two_outcomes_is_rejected() -> None:
    pair = (
        build_case(category="text_normalization", normalization_group="split"),
        build_case(
            id="second-case",
            category="text_normalization",
            question="WHAT IS RECIPROCAL RANK FUSION?",
            normalization_group="split",
            expected_terminal_status="refused",
            expected_stop_reason="no_evidence",
            expected_min_citations=0,
            expected_max_citations=0,
            expected_chunk_ids=[],
            expected_source_paths=[],
        ),
    )
    assert "group_expects_divergence" in codes(pair)


def test_a_shrunken_dataset_is_rejected() -> None:
    errors = validate_dataset((build_case(),), minimum_cases=48, required_categories=())
    assert "dataset_too_small" in {error.code for error in errors}


def test_a_missing_slice_is_rejected() -> None:
    errors = validate_dataset(
        (build_case(),),
        minimum_cases=MINIMUM,
        required_categories=("multi_concept",),
    )
    assert "missing_category" in {error.code for error in errors}


def test_unparsable_lines_are_reported_rather_than_skipped(tmp_path: Path) -> None:
    path = tmp_path / "broken.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(case_payload()),
                "{not json at all",
                json.dumps([1, 2, 3]),
                json.dumps(case_payload(id="missing-rationale", rationale="short")),
                "",
            ]
        ),
        encoding="utf-8",
    )
    cases, errors = read_cases(path)
    assert len(cases) == 1
    assert {error.code for error in errors} == {
        "unparsable_line",
        "not_an_object",
        "schema_violation",
    }


def test_loading_a_broken_dataset_raises_rather_than_returning_it(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.jsonl"
    path.write_text(
        "\n".join([json.dumps(case_payload()), json.dumps(case_payload())]),
        encoding="utf-8",
    )
    with pytest.raises(DatasetInvalid) as raised:
        load_dataset(path, minimum_cases=MINIMUM)
    assert any(error.code == "duplicate_id" for error in raised.value.errors)


def test_a_missing_dataset_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_dataset(tmp_path / "absent.jsonl")


def test_the_digest_survives_a_checkout_that_changes_line_endings(tmp_path: Path) -> None:
    """The same dataset must have the same identity on Windows and on Linux."""
    line = json.dumps(case_payload())
    unix = tmp_path / "unix.jsonl"
    unix.write_bytes(f"{line}\n".encode())
    windows = tmp_path / "windows.jsonl"
    windows.write_bytes(f"{line}\r\n".encode())
    assert unix.read_bytes() != windows.read_bytes()
    assert file_digest(unix) == file_digest(windows)


def test_the_digest_moves_when_the_curation_moves(tmp_path: Path) -> None:
    """Line endings are the only thing it forgives."""
    first = tmp_path / "first.jsonl"
    first.write_bytes((json.dumps(case_payload()) + "\n").encode())
    second = tmp_path / "second.jsonl"
    second.write_bytes(
        (json.dumps(case_payload(question="Explain reranking.")) + "\n").encode()
    )
    assert file_digest(first) != file_digest(second)
