"""Does the harness notice when the system under evaluation is wrong?

A scorecard that reports a clean sweep is worth exactly as much as its ability to
report something else. Every test here points the evaluation at an implementation
that is broken in a known way and asserts the scorecard *falls*, naming the metric
that should have moved.

This is the anti-reward-hacking half of the suite. The other half — the dataset
tests — checks that expectations were derived rather than recorded. Between them:
a case cannot be written to match whatever the code does, and a harness cannot
pass everything regardless of what the code does.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from broken_runners import BROKEN_RUNNERS, always_refuses, fabricates_citations

from agentic_rag.evals.dataset import EvalDataset, load_dataset
from agentic_rag.evals.results import MetricValue, Scorecard
from agentic_rag.evals.runner import build_scorecard, default_runner, gate_failures

DATASET_PATH = Path("data/eval/golden_research.jsonl")


@pytest.fixture(scope="module")
def dataset() -> EvalDataset:
    return load_dataset(DATASET_PATH)


def metric(scorecard: Scorecard, name: str) -> MetricValue:
    return next(value for value in scorecard.metrics if value.id == name)


@pytest.fixture(scope="module")
def honest(dataset: EvalDataset) -> Scorecard:
    return build_scorecard(dataset, repeats=1, runner=default_runner)


def test_the_honest_implementation_passes(honest: Scorecard) -> None:
    """The reference point. Every claim below is relative to this."""
    assert gate_failures(honest) == ()
    assert metric(honest, "all_declared_expectations_met").value == 1.0


@pytest.mark.parametrize("name", sorted(BROKEN_RUNNERS))
def test_every_broken_implementation_is_caught(
    dataset: EvalDataset, honest: Scorecard, name: str
) -> None:
    """Each broken loop must fail a gate, drop agreement, or both.

    A broken implementation that produces the same scorecard as the honest one
    means this harness measures nothing about that defect.
    """
    scorecard = build_scorecard(dataset, repeats=1, runner=BROKEN_RUNNERS[name])
    failed_gates = gate_failures(scorecard)
    agreement = metric(scorecard, "all_declared_expectations_met").value
    honest_agreement = metric(honest, "all_declared_expectations_met").value
    assert failed_gates or (agreement is not None and agreement < (honest_agreement or 1.0)), (
        f"{name} produced a scorecard indistinguishable from the honest run"
    )


def test_refusing_everything_is_caught_by_the_metrics_not_the_gates(
    dataset: EvalDataset,
) -> None:
    """Refusal is structurally valid, so only the expectations can catch this.

    The number that has to move is ``unexpected_refusal_rate``: refusing where the
    rules imply an answer. A harness with only invariants would pass a loop that
    answers nothing, which is the cheapest possible way to look safe.
    """
    scorecard = build_scorecard(dataset, repeats=1, runner=always_refuses)
    assert gate_failures(scorecard) == ()
    unexpected = metric(scorecard, "unexpected_refusal_rate")
    assert unexpected.denominator > 0
    assert unexpected.value == 1.0
    assert (metric(scorecard, "all_declared_expectations_met").value or 0.0) < 1.0
    assert metric(scorecard, "citation_marker_validity").denominator == 0


def test_fabricated_citations_fail_the_gates(dataset: EvalDataset) -> None:
    scorecard = build_scorecard(dataset, repeats=1, runner=fabricates_citations)
    broken = {outcome.id for outcome in scorecard.failed_invariants}
    assert {"citations_resolve", "provenance_is_real"} <= broken
    assert gate_failures(scorecard)


def test_strict_mode_fails_on_expectation_mismatch_alone(dataset: EvalDataset) -> None:
    """``--strict`` exists only in the stricter direction, and is proven to bite."""
    scorecard = build_scorecard(dataset, repeats=1, runner=always_refuses)
    assert gate_failures(scorecard, strict=False) == ()
    assert gate_failures(scorecard, strict=True)


def test_a_broken_run_never_reports_a_free_path_it_did_not_take(
    dataset: EvalDataset,
) -> None:
    """A loop that retrieves nothing cannot claim the fixture served it."""
    scorecard = build_scorecard(dataset, repeats=1, runner=always_refuses)
    free_path = metric(scorecard, "free_path_share")
    assert free_path.denominator == 0
    assert free_path.value is None
    assert free_path.undefined_reason
