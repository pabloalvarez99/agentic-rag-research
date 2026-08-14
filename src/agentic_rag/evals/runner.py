"""Run deterministic goldens and compute transparent behavioral metrics."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from agentic_rag.agent import run_research
from agentic_rag.evals.dataset import DEFAULT_DATASET, load_dataset
from agentic_rag.evals.models import CaseResult, EvalMetrics, EvalReport, GoldenCase
from agentic_rag.tools import FakeRetrievalBackend, RetrieveTool


def evaluate_case(case: GoldenCase) -> CaseResult:
    """Evaluate one case using a freshly constructed, network-free fake backend."""
    state = run_research(
        case.question,
        tool=RetrieveTool(FakeRetrievalBackend()),
        max_steps=case.max_steps,
        top_k=case.top_k,
    )
    if state.stop_reason is None:
        raise RuntimeError(f"case {case.id!r} did not record a stop reason")

    citation_ids = {citation.chunk_id for citation in state.citations if citation.chunk_id}
    source_paths = {citation.source_path for citation in state.citations}
    gap_kinds = {gap.kind for gap in state.gaps}
    citation_count = len(state.citations)
    expected = case.expect
    failures: list[str] = []

    _expect_equal(failures, "status", state.status.value, expected.status)
    _expect_equal(failures, "stop_reason", state.stop_reason, expected.stop_reason)
    _expect_equal(failures, "steps_used", state.steps_taken, expected.steps_used)
    if not expected.min_citations <= citation_count <= expected.max_citations:
        failures.append(
            f"citation_count={citation_count!r}, expected "
            f"[{expected.min_citations}, {expected.max_citations}]"
        )
    if expected.cite_chunk_ids_any and citation_ids.isdisjoint(expected.cite_chunk_ids_any):
        failures.append(
            f"citation chunk ids {sorted(citation_ids)!r} contain none of "
            f"{sorted(expected.cite_chunk_ids_any)!r}"
        )
    if len(source_paths) < expected.min_distinct_sources:
        failures.append(
            f"distinct_sources={len(source_paths)!r}, expected >= {expected.min_distinct_sources!r}"
        )
    if expected.gap_kinds_any and gap_kinds.isdisjoint(expected.gap_kinds_any):
        failures.append(
            f"gap kinds {sorted(gap_kinds)!r} contain none of {sorted(expected.gap_kinds_any)!r}"
        )

    return CaseResult(
        id=case.id,
        category=case.category,
        status=state.status.value,
        stop_reason=state.stop_reason,
        steps_used=state.steps_taken,
        has_citations=bool(state.citations),
        citation_count=citation_count,
        passed=not failures,
        failures=tuple(failures),
    )


def _expect_equal(failures: list[str], field: str, actual: object, expected: object) -> None:
    """Record a stable equality failure without hiding either value."""
    if actual != expected:
        failures.append(f"{field}={actual!r}, expected {expected!r}")


def evaluate(path: Path = DEFAULT_DATASET) -> EvalReport:
    """Evaluate ``path`` and aggregate steps, citation presence, and stop status."""
    results = tuple(evaluate_case(case) for case in load_dataset(path))
    total = len(results)
    passed = sum(result.passed for result in results)
    steps = sum(result.steps_used for result in results)
    cited = sum(result.has_citations for result in results)
    status_counts = dict(sorted(Counter(result.status for result in results).items()))
    metrics = EvalMetrics(
        total_cases=total,
        passed_cases=passed,
        pass_rate=passed / total,
        mean_steps_used=steps / total,
        has_citations_rate=cited / total,
        status_counts=status_counts,
    )
    return EvalReport(dataset=path.as_posix(), metrics=metrics, results=results)


__all__ = ["evaluate", "evaluate_case"]
