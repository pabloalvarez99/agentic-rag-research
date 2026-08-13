"""The runner, the artifact it writes, and the properties the artifact claims."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentic_rag.evals.dataset import EvalDataset, load_dataset
from agentic_rag.evals.results import (
    NORMALIZED,
    RESULTS_SCHEMA_VERSION,
    VOLATILE_FIELDS,
    canonical_json,
    digest_of,
    scorecard_payload,
    write_json,
    write_text,
)
from agentic_rag.evals.runner import (
    DISCLAIMER,
    build_fixture_tool,
    build_scorecard,
    compare,
    default_runner,
    digest_results,
    evaluate_case,
    evaluate_dataset,
    observe,
    summary_lines,
)

DATASET_PATH = Path("data/eval/golden_research.jsonl")


@pytest.fixture(scope="module")
def dataset() -> EvalDataset:
    return load_dataset(DATASET_PATH)


@pytest.fixture(scope="module")
def payload(dataset: EvalDataset) -> dict[str, object]:
    scorecard = build_scorecard(dataset, repeats=2, reproducible=True, command="pytest")
    return scorecard_payload(scorecard)


def test_a_case_record_carries_no_report_text(dataset: EvalDataset) -> None:
    """Reports are digested, never stored: an artifact is not a transcript."""
    result = evaluate_case(dataset.cases[0])
    dumped = json.dumps(result.model_dump(mode="json"))
    assert "report_sha256" in dumped
    assert result.observed.report_sha256.startswith("sha256:")
    assert "snippet" not in dumped


def test_observing_a_run_records_the_backend_that_served_it() -> None:
    state = default_runner("What is reciprocal rank fusion?", build_fixture_tool(), 4, 5)
    observed = observe(state)
    assert observed.backends == ("fake",)
    assert observed.steps_used == 1


def test_comparison_reports_none_where_a_case_declared_nothing(
    dataset: EvalDataset,
) -> None:
    """An undeclared constraint is not a met one, and must not count as agreement."""
    case = next(case for case in dataset if not case.expected_chunk_ids)
    state = default_runner(case.question, build_fixture_tool(), case.max_steps, case.top_k)
    match = compare(case, observe(state))
    assert match.expected_chunks is None
    assert match.all_declared_met is (
        match.terminal_status and match.stop_reason and match.citation_bounds
    )


def test_evaluating_the_dataset_preserves_file_order(dataset: EvalDataset) -> None:
    results = evaluate_dataset(dataset)
    assert [result.id for result in results] == [case.id for case in dataset]


def test_repeating_the_dataset_produces_the_same_digest(dataset: EvalDataset) -> None:
    first = digest_results(evaluate_dataset(dataset))
    second = digest_results(evaluate_dataset(dataset))
    assert first == second


def test_a_single_pass_reports_determinism_as_unproven(dataset: EvalDataset) -> None:
    scorecard = build_scorecard(dataset, repeats=1)
    assert scorecard.determinism.stable is True
    assert scorecard.determinism.proven is False
    assert "unproven" in " ".join(summary_lines(scorecard))


def test_repeats_below_one_are_refused(dataset: EvalDataset) -> None:
    with pytest.raises(ValueError, match="at least once"):
        build_scorecard(dataset, repeats=0)


def test_the_artifact_declares_what_it_is(payload: dict[str, Any]) -> None:
    assert payload["schema_version"] == RESULTS_SCHEMA_VERSION
    assert payload["evidence_class"] == "fixture-contract"
    assert payload["disclaimer"] == DISCLAIMER
    assert tuple(payload["volatile_fields"]) == VOLATILE_FIELDS


def test_the_artifact_states_the_free_path_it_took(payload: dict[str, Any]) -> None:
    run = payload["run"]
    assert run["network_used"] is False
    assert run["billed_usd"] == 0.0
    assert run["backend"] == "fake"


def test_reproducible_mode_normalizes_exactly_the_volatile_fields(
    payload: dict[str, Any],
) -> None:
    run = payload["run"]
    assert run["generated_at"] == NORMALIZED
    assert run["python_version"] == NORMALIZED
    assert run["platform"] == NORMALIZED
    assert run["package_version"] != NORMALIZED


def test_no_field_anywhere_records_a_duration(payload: dict[str, Any]) -> None:
    """A timing in the artifact invites a latency claim a fixture cannot support.

    Keys are inspected rather than the whole document: the disclaimer says the
    word "latency" on purpose, to deny measuring it.
    """

    def keys(node: object) -> set[str]:
        if isinstance(node, dict):
            found = set(node)
            for value in node.values():
                found |= keys(value)
            return found
        if isinstance(node, list):
            return {name for item in node for name in keys(item)}
        return set()

    timing = {"duration", "elapsed", "latency", "seconds", "millis", "took"}
    offending = {
        key for key in keys(payload) if any(word in key.lower() for word in timing)
    }
    assert offending == set()


def test_the_digest_ignores_the_volatile_fields_and_itself(dataset: EvalDataset) -> None:
    first = scorecard_payload(build_scorecard(dataset, repeats=1, command="one"))
    second = scorecard_payload(build_scorecard(dataset, repeats=1, command="one"))
    assert first["results_digest"] == second["results_digest"]
    assert first["run"]["generated_at"] != NORMALIZED

    recomputed = digest_of(first, ignore=VOLATILE_FIELDS)
    assert recomputed == first["results_digest"]


def test_the_digest_changes_when_a_scored_fact_changes(dataset: EvalDataset) -> None:
    """A digest that never moves proves nothing about what it covers."""
    payload = scorecard_payload(build_scorecard(dataset, repeats=1))
    altered = json.loads(json.dumps(payload))
    altered["cases"][0]["observed"]["steps_used"] += 1
    assert digest_of(altered, ignore=VOLATILE_FIELDS) != payload["results_digest"]


def test_every_metric_states_its_denominator(payload: dict[str, Any]) -> None:
    for metric in payload["metrics"]:
        assert metric["denominator_meaning"]
        assert metric["description"].endswith(".")
        if metric["denominator"] == 0:
            assert metric["value"] is None
            assert metric["undefined_reason"]
        else:
            assert metric["value"] == pytest.approx(
                metric["numerator"] / metric["denominator"], abs=1e-6
            )


def test_empty_slices_are_listed_rather_than_dropped(dataset: EvalDataset) -> None:
    """A slice with no case reads as missing coverage, not as a clean sweep."""
    single = [case for case in dataset if case.category == "multi_concept"][:1]
    subset = EvalDataset(path=dataset.path, sha256=dataset.sha256, cases=tuple(single))
    payload = scorecard_payload(build_scorecard(subset, repeats=1))
    empty = payload["metrics_by_category"]["duplicate_evidence"]
    assert empty
    assert all(metric["value"] is None for metric in empty)


def test_canonical_json_is_order_independent() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_writes_are_atomic_and_leave_no_temporary(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "latest.json"
    text = write_json(target, {"a": 1})
    assert target.read_text(encoding="utf-8") == text
    assert text.endswith("\n")
    assert not list(tmp_path.rglob("*.tmp"))

    markdown = tmp_path / "nested" / "latest.md"
    write_text(markdown, "# title\n")
    assert markdown.read_text(encoding="utf-8") == "# title\n"
    assert not list(tmp_path.rglob("*.tmp"))


def test_an_interrupted_write_leaves_the_previous_artifact_intact(tmp_path: Path) -> None:
    target = tmp_path / "latest.json"
    write_json(target, {"pass": 1})
    with pytest.raises(TypeError):
        write_json(target, {"pass": object()})
    assert json.loads(target.read_text(encoding="utf-8")) == {"pass": 1}
