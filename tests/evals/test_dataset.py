"""Golden dataset schema and integrity tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_rag.evals.dataset import DEFAULT_DATASET, DatasetError, load_dataset


def test_committed_dataset_is_strict_and_covers_the_required_slices() -> None:
    cases = load_dataset()

    assert len(cases) >= 40
    assert len({case.id for case in cases}) == len(cases)
    assert {
        "answerable_multi_hop",
        "unanswerable",
        "budget_stress",
        "thin_evidence",
        "tool_budget",
    } <= {case.category for case in cases}
    critic_case = next(case for case in cases if case.id == "critic-notes-exist-not-success")
    assert critic_case.expect.status == "refused"
    assert critic_case.expect.min_citations >= 1
    assert DEFAULT_DATASET.name == "golden_research.jsonl"


def test_unknown_fields_fail_instead_of_drifting_silently(tmp_path: Path) -> None:
    record = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8").splitlines()[0])
    record["unexpected"] = True
    dataset = tmp_path / "drift.jsonl"
    dataset.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(DatasetError, match="unexpected"):
        load_dataset(dataset)
