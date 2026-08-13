"""The scorecard a person reads: a projection of the JSON, with its limits attached.

Two things are asserted here. The Markdown must not invent a number the JSON does
not contain — it is a projection, not a second computation. And it must carry the
labels that stop a fixture result from being quoted as a quality result, including
refusing to print ``$0 billed`` unless the records prove the free path was taken.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from broken_runners import always_refuses, fabricates_citations

from agentic_rag.evals.dataset import EvalDataset, load_dataset
from agentic_rag.evals.render import UNDEFINED, render_markdown
from agentic_rag.evals.results import scorecard_payload
from agentic_rag.evals.runner import build_scorecard, default_runner

DATASET_PATH = Path("data/eval/golden_research.jsonl")


@pytest.fixture(scope="module")
def dataset() -> EvalDataset:
    return load_dataset(DATASET_PATH)


@pytest.fixture(scope="module")
def payload(dataset: EvalDataset) -> dict[str, Any]:
    return scorecard_payload(
        build_scorecard(dataset, repeats=3, reproducible=True, command="pytest")
    )


@pytest.fixture(scope="module")
def markdown(payload: dict[str, Any]) -> str:
    return render_markdown(payload)


def test_the_first_thing_it_says_is_what_it_is(markdown: str) -> None:
    head = markdown.splitlines()[:4]
    assert any("Evidence class: fixture-contract" in line for line in head)
    assert any("not a measurement of retrieval quality" in line for line in head)


def test_it_names_what_it_does_not_measure(markdown: str) -> None:
    for claim in (
        "Retrieval quality",
        "Answer quality",
        "Latency",
        "Production readiness",
        "comparison with another system",
    ):
        assert claim in markdown


def test_it_never_claims_a_state_of_the_art(markdown: str) -> None:
    lowered = markdown.lower()
    for forbidden in ("sota", "state of the art", "state-of-the-art", "outperform", "beats "):
        assert forbidden not in lowered


def test_it_prints_the_dataset_identity(payload: dict[str, Any], markdown: str) -> None:
    assert payload["dataset"]["sha256"] in markdown
    assert payload["results_digest"] in markdown
    assert str(payload["dataset"]["case_count"]) in markdown


def test_every_rate_is_printed_with_its_arithmetic(payload: dict[str, Any], markdown: str) -> None:
    for metric in payload["metrics"]:
        if metric["value"] is None:
            continue
        assert f"({metric['numerator']}/{metric['denominator']})" in markdown


def test_an_undefined_rate_prints_as_undefined_not_as_perfect(dataset: EvalDataset) -> None:
    """A slice with no case must not read as 100%."""
    single = [case for case in dataset if case.category == "multi_concept"][:1]
    subset = EvalDataset(path=dataset.path, sha256=dataset.sha256, cases=tuple(single))
    rendered = render_markdown(scorecard_payload(build_scorecard(subset, repeats=1)))
    assert UNDEFINED in rendered
    assert "0 denominator" in rendered


def test_the_zero_cost_line_needs_the_free_path_to_be_proven(markdown: str) -> None:
    assert "$0 billed" in markdown


def test_a_run_that_retrieved_nothing_may_not_claim_zero_cost(
    dataset: EvalDataset,
) -> None:
    """The claim rests on the records, not on the code path looking free."""
    rendered = render_markdown(
        scorecard_payload(build_scorecard(dataset, repeats=1, runner=always_refuses))
    )
    assert "$0 billed" not in rendered
    assert "cost not established" in rendered


def test_a_single_pass_is_rendered_as_unproven(dataset: EvalDataset) -> None:
    rendered = render_markdown(scorecard_payload(build_scorecard(dataset, repeats=1)))
    assert "unproven" in rendered


def test_repeats_are_rendered_as_stable_with_their_digests(
    payload: dict[str, Any], markdown: str
) -> None:
    assert "stable across 3 passes" in markdown
    for digest in payload["determinism"]["digests"]:
        assert digest in markdown


def test_violations_are_printed_in_full_rather_than_counted(dataset: EvalDataset) -> None:
    rendered = render_markdown(
        scorecard_payload(build_scorecard(dataset, repeats=1, runner=fabricates_citations))
    )
    assert "### Violations" in rendered
    assert "invented-1" in rendered
    assert "**" in rendered


def test_the_baseline_is_labelled_as_control_flow_only(markdown: str) -> None:
    assert "Single-pass reference" in markdown
    assert "control-flow" in markdown
    assert "supports no statement about answer quality" in markdown


def test_every_case_appears_in_the_table(payload: dict[str, Any], markdown: str) -> None:
    for case in payload["cases"]:
        assert f"`{case['id']}`" in markdown


def test_rendering_is_a_pure_function_of_the_document(payload: dict[str, Any]) -> None:
    copied = json.loads(json.dumps(payload))
    assert render_markdown(copied) == render_markdown(payload)


def test_rendering_ends_with_exactly_one_newline(markdown: str) -> None:
    assert markdown.endswith("\n")
    assert not markdown.endswith("\n\n")


def test_the_honest_run_is_the_one_being_rendered(dataset: EvalDataset) -> None:
    """Guards against the fixture drifting away from the default implementation."""
    scorecard = build_scorecard(dataset, repeats=1, runner=default_runner)
    assert scorecard.failed_invariants == ()
