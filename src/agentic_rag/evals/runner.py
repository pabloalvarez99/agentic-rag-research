"""Running the dataset: one finished loop per case, reduced to a checkable record.

The runner is deliberately dull. It binds a backend explicitly, walks the cases in
file order, and writes down what happened. Three choices in here are not dull, and
each is a property the artifact depends on:

* **The backend is constructed, never discovered.** ``build_retrieve_tool()`` reads
  ``PRODUCTION_RAG_URL`` and would silently send an evaluation over the network if
  a shell happened to have it set. This module never calls it. The fixture is
  passed in, and every run's own trace is checked afterwards to prove which backend
  actually served it — a claim about being offline that rests on the code path
  alone is a claim nobody can audit from the artifact.
* **Determinism is measured, not assumed.** ``--repeat n`` evaluates the whole
  dataset n times and digests the case records of each pass. Sameness across passes
  is the evidence; a single pass proves nothing and is reported as unproven rather
  than as stable.
* **Nothing here knows a case id.** The runner takes a dataset path and treats every
  case identically. Special-casing one case in the harness is how a scorecard comes
  to describe the harness instead of the system.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Final

from agentic_rag import __version__
from agentic_rag.agent import ResearchState, run_research
from agentic_rag.evals.baseline import run_baseline
from agentic_rag.evals.dataset import DATASET_SCHEMA_VERSION, EvalCase, EvalDataset
from agentic_rag.evals.invariants import (
    DATASET_INVARIANT_IDS,
    INVARIANTS,
    RunContext,
    check_run,
)
from agentic_rag.evals.metrics import (
    CasePair,
    compute_metrics,
    compute_metrics_by_category,
    steps_distribution,
)
from agentic_rag.evals.results import (
    NORMALIZED,
    VOLATILE_FIELDS,
    CaseResult,
    DatasetMetadata,
    DeterminismOutcome,
    ExpectationMatch,
    InvariantOutcome,
    ObservedRun,
    RunMetadata,
    Scorecard,
    canonical_json,
)
from agentic_rag.tools import DEFAULT_CORPUS, Document, FakeRetrievalBackend, RetrieveTool

DISCLAIMER: Final = (
    "Fixture-contract evidence. Every number below describes the agent's control plane — "
    "stop decisions, budgets, citation resolution, traces, determinism — measured against a "
    "deterministic in-process retrieval fixture over a small committed corpus. It is not a "
    "measurement of retrieval quality, answer quality, faithfulness, latency or production "
    "readiness, and no number here supports a comparison with any other system."
)
"""Printed at the top of every artifact this runner writes."""

ResearchRunner = Callable[[str, RetrieveTool, int, int], ResearchState]
"""The system under evaluation: a question and its controls in, a finished run out."""


def default_runner(question: str, tool: RetrieveTool, max_steps: int, top_k: int) -> ResearchState:
    """Run the agent loop for one case.

    Args:
        question: The research question, unmodified.
        tool: The retrieve tool, already bound to a backend.
        max_steps: Step budget for this run.
        top_k: Passages one retrieval step may return.

    Returns:
        The finished state.
    """
    return run_research(question, tool=tool, max_steps=max_steps, top_k=top_k)


def build_fixture_tool(corpus: Sequence[Document] = DEFAULT_CORPUS) -> RetrieveTool:
    """Return a retrieve tool bound to the in-process fixture, reading no environment.

    Args:
        corpus: Documents the fixture searches.

    Returns:
        A tool that contacts nothing.
    """
    return RetrieveTool(FakeRetrievalBackend(corpus))


def _repeated_evidence_ids(state: ResearchState) -> tuple[str, ...]:
    """Return chunk ids more than one step returned, which the state must store once."""
    seen: set[str] = set()
    repeated: set[str] = set()
    for step in state.steps:
        for chunk_id in set(step.evidence_ids):
            if chunk_id in seen:
                repeated.add(chunk_id)
            seen.add(chunk_id)
    return tuple(sorted(repeated))


def observe(state: ResearchState) -> ObservedRun:
    """Reduce a finished run to the facts a scorecard records.

    Args:
        state: The finished state.

    Returns:
        The observation, carrying a digest of the report rather than its text.
    """
    report = state.report or ""
    backends = sorted(
        {
            str(event.payload.get("backend"))
            for event in state.trace
            if event.event == "tool_result"
        }
    )
    return ObservedRun(
        status=state.status.value,
        stop_reason=state.stop_reason,
        steps_used=state.steps_taken,
        plan_size=len(state.plan),
        evidence_ids=tuple(state.evidence_ids),
        citation_markers=tuple(citation.marker for citation in state.citations),
        citation_chunk_ids=tuple(citation.chunk_id or "" for citation in state.citations),
        citation_source_paths=tuple(citation.source_path for citation in state.citations),
        repeated_evidence_ids=_repeated_evidence_ids(state),
        gap_kinds=tuple(gap.kind for gap in state.gaps),
        trace_events=tuple(event.event for event in state.trace),
        backends=tuple(backends),
        report_sha256=f"sha256:{sha256(report.encode('utf-8')).hexdigest()}",
        report_line_count=len(report.splitlines()),
    )


def compare(case: EvalCase, observed: ObservedRun) -> ExpectationMatch:
    """Return which of the case's declared constraints the run met.

    Args:
        case: The case and its constraints.
        observed: What the run did.

    Returns:
        One flag per constraint; ``None`` where the case declared none.
    """
    citation_count = len(observed.citation_markers)
    within_bounds = citation_count >= case.expected_min_citations and (
        case.expected_max_citations is None or citation_count <= case.expected_max_citations
    )
    return ExpectationMatch(
        terminal_status=observed.status == case.expected_terminal_status,
        stop_reason=observed.stop_reason == case.expected_stop_reason,
        min_plan_size=observed.plan_size >= case.expected_min_plan_size,
        citation_bounds=within_bounds,
        expected_sources=(
            set(case.expected_source_paths) <= set(observed.citation_source_paths)
            if case.expected_source_paths
            else None
        ),
        expected_chunks=(
            set(case.expected_chunk_ids) <= set(observed.evidence_ids)
            if case.expected_chunk_ids
            else None
        ),
        repeated_evidence=(
            bool(observed.repeated_evidence_ids) if case.expects_repeated_evidence else None
        ),
    )


def evaluate_case(
    case: EvalCase,
    *,
    corpus: Sequence[Document] = DEFAULT_CORPUS,
    runner: ResearchRunner = default_runner,
    tool_factory: Callable[[Sequence[Document]], RetrieveTool] = build_fixture_tool,
) -> CaseResult:
    """Run one case and return its record.

    Args:
        case: The case to evaluate.
        corpus: The fixture the run and the baseline both retrieve from.
        runner: The system under evaluation. Injectable so a deliberately broken
            implementation can be pointed at this harness, which is how the
            harness is shown to have any discriminating power at all.
        tool_factory: Builds the retrieve tool from the corpus.

    Returns:
        The case record, including invariant violations and the single-pass
        reference for the same question.
    """
    tool = tool_factory(corpus)
    state = runner(case.question, tool, case.max_steps, case.top_k)
    observed = observe(state)
    violations = check_run(
        RunContext(case=case, state=state, corpus=corpus, backend_name=tool.backend_name)
    )
    baseline = run_baseline(tool_factory(corpus), case.question, top_k=case.top_k)
    return CaseResult(
        id=case.id,
        category=case.category,
        question=case.question,
        max_steps=case.max_steps,
        top_k=case.top_k,
        expected={
            "terminal_status": case.expected_terminal_status,
            "stop_reason": case.expected_stop_reason,
            "min_citations": case.expected_min_citations,
            "max_citations": case.expected_max_citations,
            "source_paths": list(case.expected_source_paths),
            "chunk_ids": list(case.expected_chunk_ids),
            "min_plan_size": case.expected_min_plan_size,
            "repeated_evidence": case.expects_repeated_evidence,
            "normalization_group": case.normalization_group,
            "rationale": case.rationale,
        },
        observed=observed,
        matches=compare(case, observed),
        invariant_violations=violations,
        baseline={
            "label": baseline.label,
            "evidence_ids": list(baseline.evidence_ids),
            "evidence_count": baseline.evidence_count,
            "source_paths": list(baseline.source_paths),
        },
    )


def evaluate_dataset(
    dataset: EvalDataset,
    *,
    corpus: Sequence[Document] = DEFAULT_CORPUS,
    runner: ResearchRunner = default_runner,
    tool_factory: Callable[[Sequence[Document]], RetrieveTool] = build_fixture_tool,
) -> tuple[CaseResult, ...]:
    """Run every case in file order.

    Args:
        dataset: The validated dataset.
        corpus: The fixture every case retrieves from.
        runner: The system under evaluation.
        tool_factory: Builds the retrieve tool from the corpus.

    Returns:
        One record per case, in dataset order.
    """
    return tuple(
        evaluate_case(case, corpus=corpus, runner=runner, tool_factory=tool_factory)
        for case in dataset.cases
    )


def digest_results(results: Sequence[CaseResult]) -> str:
    """Return a digest over case records, for comparing one pass against another.

    Args:
        results: Case records from one pass over the dataset.

    Returns:
        A hex digest prefixed with its algorithm. It covers the records only, so
        it is unaffected by when or where the evaluation ran.
    """
    payload = [result.model_dump(mode="json") for result in results]
    encoded = canonical_json({"cases": payload}).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _invariant_outcomes(
    results: Sequence[CaseResult],
    determinism: DeterminismOutcome,
    surface_violations: Sequence[str],
) -> tuple[InvariantOutcome, ...]:
    """Return one outcome per invariant, per-case ones first."""
    outcomes: list[InvariantOutcome] = []
    for invariant in INVARIANTS:
        messages: list[str] = []
        violating = 0
        for result in results:
            found = result.invariant_violations.get(invariant.id, ())
            if found:
                violating += 1
                messages.extend(f"{result.id}: {message}" for message in found)
        outcomes.append(
            InvariantOutcome(
                id=invariant.id,
                description=invariant.description,
                cases_checked=len(results),
                cases_violating=violating,
                violations=tuple(messages),
            )
        )

    outcomes.append(
        InvariantOutcome(
            id=DATASET_INVARIANT_IDS[0],
            description=(
                "Repeating the whole evaluation produces byte-identical case records."
            ),
            cases_checked=determinism.repeats,
            cases_violating=0 if determinism.stable else determinism.repeats,
            violations=(
                ()
                if determinism.stable
                else (f"case records differ across repeats: {list(determinism.digests)}",)
            ),
        )
    )
    outcomes.append(
        InvariantOutcome(
            id=DATASET_INVARIANT_IDS[1],
            description=(
                "Cases differing only in surface form produce the same outcome and evidence."
            ),
            cases_checked=len(results),
            cases_violating=len(surface_violations),
            violations=tuple(surface_violations),
        )
    )
    return tuple(outcomes)


def _surface_form_violations(pairs: Sequence[CasePair]) -> tuple[str, ...]:
    """Return every way a normalization group's members disagreed with each other."""
    groups: dict[str, list[CasePair]] = {}
    for case, result in pairs:
        if case.normalization_group is not None:
            groups.setdefault(case.normalization_group, []).append((case, result))

    problems: list[str] = []
    for name, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        head_case, head = members[0]
        for _, member in members[1:]:
            if (
                member.observed.status,
                member.observed.stop_reason,
                member.observed.evidence_ids,
                member.observed.citation_chunk_ids,
            ) != (
                head.observed.status,
                head.observed.stop_reason,
                head.observed.evidence_ids,
                head.observed.citation_chunk_ids,
            ):
                problems.append(
                    f"{member.id}: surface variant behaves differently from {head_case.id} "
                    f"in group {name!r}"
                )
    return tuple(problems)


def build_scorecard(
    dataset: EvalDataset,
    *,
    repeats: int = 1,
    corpus: Sequence[Document] = DEFAULT_CORPUS,
    runner: ResearchRunner = default_runner,
    tool_factory: Callable[[Sequence[Document]], RetrieveTool] = build_fixture_tool,
    command: str = "",
    reproducible: bool = False,
) -> Scorecard:
    """Evaluate a dataset, repeat it, and assemble the artifact.

    Args:
        dataset: The validated dataset.
        repeats: How many times to evaluate the whole dataset. More than one is
            what turns "deterministic" from an adjective into a measurement.
        corpus: The fixture every case retrieves from.
        runner: The system under evaluation.
        tool_factory: Builds the retrieve tool from the corpus.
        command: The command being run, recorded for provenance.
        reproducible: Write volatile fields as a fixed placeholder so two clean
            clones can diff the artifact byte for byte.

    Returns:
        The scorecard for the first pass, with determinism measured across all of
        them. The first pass is reported rather than the last so a reader is
        looking at the run the digests were compared against.

    Raises:
        ValueError: ``repeats`` is below one.
    """
    if repeats < 1:
        raise ValueError("an evaluation runs at least once")

    passes: list[tuple[CaseResult, ...]] = []
    digests: list[str] = []
    for _ in range(repeats):
        results = evaluate_dataset(
            dataset, corpus=corpus, runner=runner, tool_factory=tool_factory
        )
        passes.append(results)
        digests.append(digest_results(results))

    results = passes[0]
    pairs: list[CasePair] = list(zip(dataset.cases, results, strict=True))
    determinism = DeterminismOutcome(
        repeats=repeats,
        digests=tuple(digests),
        stable=len(set(digests)) == 1,
    )
    backend = tool_factory(corpus).backend_name

    now = datetime.now(UTC).isoformat(timespec="seconds")
    return Scorecard(
        volatile_fields=VOLATILE_FIELDS,
        disclaimer=DISCLAIMER,
        run=RunMetadata(
            generated_at=NORMALIZED if reproducible else now,
            python_version=NORMALIZED if reproducible else sys.version.split()[0],
            platform=NORMALIZED if reproducible else platform.platform(terse=True),
            package_version=__version__,
            command=command,
            backend=backend,
            corpus_size=len(corpus),
            network_used=False,
            billed_usd=0.0,
            reproducible_mode=reproducible,
        ),
        dataset=DatasetMetadata(
            path=dataset.path,
            sha256=dataset.sha256,
            schema_version=DATASET_SCHEMA_VERSION,
            case_count=dataset.case_count,
            counts_by_category=dataset.counts_by_category(),
        ),
        invariants=_invariant_outcomes(results, determinism, _surface_form_violations(pairs)),
        determinism=determinism,
        metrics=compute_metrics(pairs, backend=backend),
        metrics_by_category=compute_metrics_by_category(pairs, backend=backend),
        steps_distribution=steps_distribution(pairs),
        cases=results,
    )


def gate_failures(scorecard: Scorecard, *, strict: bool = False) -> tuple[str, ...]:
    """Return the reasons this run must exit nonzero.

    Args:
        scorecard: The assembled result.
        strict: Also fail when a run did not meet a constraint its case declared.
            Off by default: an expectation mismatch is a disagreement between a
            curated fixture and an implementation, and which of the two is wrong
            is a judgement a reader makes, not an exit code.

    Returns:
        One line per reason, empty when the run passed.
    """
    reasons = [
        f"invariant {outcome.id!r} violated by {outcome.cases_violating} run(s)"
        for outcome in scorecard.failed_invariants
    ]
    if strict:
        reasons.extend(
            f"case {case.id!r} did not meet every constraint it declared"
            for case in scorecard.mismatched_cases
        )
    return tuple(reasons)


def summary_lines(scorecard: Scorecard) -> tuple[str, ...]:
    """Return a short console summary of a finished evaluation.

    Args:
        scorecard: The assembled result.

    Returns:
        Lines suitable for stdout, honest about what the numbers are.
    """
    metrics: dict[str, Any] = {metric.id: metric for metric in scorecard.metrics}
    agreement = metrics["all_declared_expectations_met"]
    lines = [
        f"cases: {scorecard.dataset.case_count}  dataset: {scorecard.dataset.sha256[:19]}",
        f"invariants: {len(scorecard.invariants) - len(scorecard.failed_invariants)}"
        f"/{len(scorecard.invariants)} held",
        f"expectations met: {agreement.numerator}/{agreement.denominator}",
        f"determinism: {'stable' if scorecard.determinism.proven else 'unproven'} "
        f"over {scorecard.determinism.repeats} repeat(s)",
        f"evidence class: {scorecard.evidence_class} (not a quality result)",
    ]
    return tuple(lines)
