"""Descriptive metrics: how often the loop met an expectation someone wrote down.

Nothing here can fail a build. These numbers describe agreement between a curated
fixture and an implementation, and agreement can drop for two opposite reasons —
the loop regressed, or the expectation was wrong. Treating that as a gate would
make the honest fix (correct the expectation) indistinguishable from the dishonest
one (loosen the threshold). The gates live in :mod:`agentic_rag.evals.invariants`.

Two rules apply to every metric below, and both exist because of the same failure:

* **The denominator is chosen so the metric can fail.** A rate over "cases that
  declared this expectation" is informative; a rate over "all cases", where most
  declare a floor of zero that anything satisfies, reports 1.0 forever. Where a
  constraint is trivially satisfiable it is not made into a metric.
* **A zero denominator is undefined, not perfect.** :meth:`MetricValue.build`
  returns ``value: null`` with the reason attached. A dataset that stopped
  covering a slice should read as missing coverage, not as a clean sweep.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence

from agentic_rag.evals.dataset import CASE_CATEGORIES, EvalCase
from agentic_rag.evals.results import CaseResult, MetricValue

CasePair = tuple[EvalCase, CaseResult]
"""A case and the result of running it, which every metric is computed from."""

CasePredicate = Callable[[EvalCase, CaseResult], bool]
"""A question asked of one evaluated case, answered yes or no."""


def _rate(
    pairs: Sequence[CasePair],
    *,
    id: str,  # noqa: A002 - the field is named `id` in the artifact
    description: str,
    denominator_meaning: str,
    applies: CasePredicate,
    satisfied: CasePredicate,
) -> MetricValue:
    """Return one metric over the pairs the predicate ``applies`` selects."""
    selected = [pair for pair in pairs if applies(*pair)]
    return MetricValue.build(
        id=id,
        description=description,
        denominator_meaning=denominator_meaning,
        numerator=sum(1 for pair in selected if satisfied(*pair)),
        denominator=len(selected),
    )


def steps_distribution(pairs: Sequence[CasePair]) -> dict[str, int]:
    """Return how many cases spent each number of steps.

    Args:
        pairs: Cases and their results.

    Returns:
        A mapping from step count, as a string key so it survives JSON, to the
        number of cases that spent it. Sorted numerically.
    """
    counted = Counter(result.observed.steps_used for _, result in pairs)
    return {str(steps): counted[steps] for steps in sorted(counted)}


def marker_counts(pairs: Sequence[CasePair]) -> tuple[int, int]:
    """Return how many citation markers were printed and how many resolve.

    A marker resolves when the report printed it, a citation claims it, and the
    chunk behind that citation is one the run actually retrieved.

    Args:
        pairs: Cases and their results.

    Returns:
        The resolving marker count and the total marker count, in that order.
    """
    resolved = 0
    total = 0
    for _, result in pairs:
        observed = result.observed
        total += len(observed.citation_markers)
        evidence = set(observed.evidence_ids)
        expected_order = tuple(range(1, len(observed.citation_markers) + 1))
        ordered = observed.citation_markers == expected_order
        for chunk_id in observed.citation_chunk_ids:
            if ordered and chunk_id in evidence:
                resolved += 1
    return resolved, total


def step_backend_counts(pairs: Sequence[CasePair], *, backend: str) -> tuple[int, int]:
    """Return how many runs were served only by ``backend``, and how many ran.

    Args:
        pairs: Cases and their results.
        backend: The backend the runner bound.

    Returns:
        Runs whose every step named ``backend``, and the number of runs that spent
        at least one step. A run that spent no step is excluded: it says nothing
        about which backend would have served it.
    """
    only = 0
    ran = 0
    for _, result in pairs:
        if result.observed.steps_used == 0:
            continue
        ran += 1
        if set(result.observed.backends) == {backend}:
            only += 1
    return only, ran


def compute_metrics(pairs: Sequence[CasePair], *, backend: str) -> tuple[MetricValue, ...]:
    """Return every descriptive metric over ``pairs``.

    Args:
        pairs: Cases and their results, in dataset order.
        backend: The retrieval backend the runner bound, for the free-path metric.

    Returns:
        The metrics, in the order a scorecard lists them.
    """
    resolved_markers, total_markers = marker_counts(pairs)
    fake_only, runs_with_steps = step_backend_counts(pairs, backend=backend)

    return (
        _rate(
            pairs,
            id="terminal_status_agreement",
            description="Runs whose terminal status was the one the case derived from the rules.",
            denominator_meaning="cases, all of which declare a terminal status",
            applies=lambda case, result: True,
            satisfied=lambda case, result: result.matches.terminal_status,
        ),
        _rate(
            pairs,
            id="stop_reason_agreement",
            description="Runs whose stop reason was the one the case derived from the rules.",
            denominator_meaning="cases, all of which declare a stop reason",
            applies=lambda case, result: True,
            satisfied=lambda case, result: result.matches.stop_reason,
        ),
        _rate(
            pairs,
            id="budget_compliance",
            description="Runs that spent no more steps than the case allowed.",
            denominator_meaning="cases, all of which set a budget",
            applies=lambda case, result: True,
            satisfied=lambda case, result: result.observed.steps_used <= case.max_steps,
        ),
        MetricValue.build(
            id="citation_marker_validity",
            description=(
                "Printed markers that are numbered in order and resolve to a retrieved chunk."
            ),
            denominator_meaning="citation markers printed across every report",
            numerator=resolved_markers,
            denominator=total_markers,
        ),
        _rate(
            pairs,
            id="expected_source_match",
            description="Runs citing every source path the case derived as necessary.",
            denominator_meaning="cases that declare expected source paths",
            applies=lambda case, result: bool(case.expected_source_paths),
            satisfied=lambda case, result: result.matches.expected_sources is True,
        ),
        _rate(
            pairs,
            id="expected_chunk_match",
            description="Runs gathering every chunk id the case derived as necessary.",
            denominator_meaning="cases that declare expected chunk ids",
            applies=lambda case, result: bool(case.expected_chunk_ids),
            satisfied=lambda case, result: result.matches.expected_chunks is True,
        ),
        _rate(
            pairs,
            id="citation_bounds_agreement",
            description="Runs whose citation count fell inside the bounds the case declared.",
            denominator_meaning="cases that bound the citation count non-trivially",
            applies=lambda case, result: (
                case.expected_min_citations > 0 or case.expected_max_citations is not None
            ),
            satisfied=lambda case, result: result.matches.citation_bounds,
        ),
        _rate(
            pairs,
            id="plan_expansion_agreement",
            description="Compound questions the planner split into at least the expected number.",
            denominator_meaning="cases expecting a plan of more than one sub-question",
            applies=lambda case, result: case.expected_min_plan_size > 1,
            satisfied=lambda case, result: result.matches.min_plan_size,
        ),
        _rate(
            pairs,
            id="repeated_evidence_dedup",
            description=(
                "Runs where one chunk came back from two steps and was stored and cited once."
            ),
            denominator_meaning="cases that expect a chunk to be returned twice",
            applies=lambda case, result: case.expects_repeated_evidence,
            satisfied=lambda case, result: result.matches.repeated_evidence is True,
        ),
        _rate(
            pairs,
            id="refusal_recall",
            description="Runs that refused where the rules say a refusal was the outcome.",
            denominator_meaning="cases expecting a refusal",
            applies=lambda case, result: case.expected_terminal_status == "refused",
            satisfied=lambda case, result: result.observed.status == "refused",
        ),
        _rate(
            pairs,
            id="unexpected_refusal_rate",
            description=(
                "Runs that refused where the rules imply an answer or a partial. Lower is better."
            ),
            denominator_meaning="cases not expecting a refusal",
            applies=lambda case, result: case.expected_terminal_status != "refused",
            satisfied=lambda case, result: result.observed.status == "refused",
        ),
        _rate(
            pairs,
            id="trace_contract_validity",
            description="Runs whose trace satisfied the recorded contract in full.",
            denominator_meaning="cases, all of which record a trace",
            applies=lambda case, result: True,
            satisfied=lambda case, result: "trace_contract" not in result.invariant_violations,
        ),
        MetricValue.build(
            id="free_path_share",
            description=(
                "Runs served exclusively by the bound in-process fixture backend. "
                "This is what a zero-cost claim rests on."
            ),
            denominator_meaning="runs that spent at least one retrieval step",
            numerator=fake_only,
            denominator=runs_with_steps,
        ),
        _rate(
            pairs,
            id="all_declared_expectations_met",
            description="Runs that met every constraint their case declared.",
            denominator_meaning="cases, all of which declare at least one constraint",
            applies=lambda case, result: True,
            satisfied=lambda case, result: result.matches.all_declared_met,
        ),
        _rate(
            pairs,
            id="invariant_clean_runs",
            description="Runs that violated no hard invariant. Any shortfall fails the run.",
            denominator_meaning="cases, all of which are checked against every invariant",
            applies=lambda case, result: True,
            satisfied=lambda case, result: result.is_clean,
        ),
    )


def compute_metrics_by_category(
    pairs: Sequence[CasePair],
    *,
    backend: str,
) -> dict[str, tuple[MetricValue, ...]]:
    """Return the same metrics restricted to each behaviour slice.

    Slices with no case are still listed, with every metric undefined. A missing
    slice is a fact about the dataset worth showing, and dropping the row is how
    it stops being visible.

    Args:
        pairs: Cases and their results.
        backend: The retrieval backend the runner bound.

    Returns:
        A mapping from category to its metrics, in declared category order.
    """
    grouped: dict[str, tuple[MetricValue, ...]] = {}
    for category in CASE_CATEGORIES:
        selected = [pair for pair in pairs if pair[0].category == category]
        grouped[category] = compute_metrics(selected, backend=backend)
    return grouped
