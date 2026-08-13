"""Hard invariants: the properties every run must have, whatever the dataset says.

This module is the half of the evaluation that can fail the build. The other half —
:mod:`agentic_rag.evals.metrics` — describes how often the loop agreed with a
curated expectation, and describing is all it does. The split matters because the
two answer different questions:

* An **invariant** is a property of *any* run over *any* question: the budget was
  not exceeded, every printed marker resolves to a passage that was retrieved, the
  trace ends with ``stop``. A violation is a defect, and no dataset curation can
  make it acceptable. These exit nonzero.
* An **agreement** is the loop meeting a human's expectation on a fixture. It can
  drop because the loop regressed, and it can equally drop because the expectation
  was wrong. That is a number to read, not a gate to trip.

Every invariant is checked against the run's own record rather than against the
call that produced it — the trace has to be able to prove the property on its own,
because the trace is what survives after the process exits.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from agentic_rag.agent import ResearchState, ResearchStatus
from agentic_rag.evals.dataset import SPEC_MAX_SUB_QUESTIONS, EvalCase
from agentic_rag.tools import Document

MARKER = re.compile(r"\[(\d+)\]")
"""The citation marker as the synthesiser prints it."""

TRACE_EVENT_NAMES: Final[frozenset[str]] = frozenset(
    {"plan_created", "tool_call", "tool_result", "critique", "synthesize", "stop"}
)
"""The closed set of trace events, restated from ``docs/architecture.md``."""

STOP_REASONS: Final[frozenset[str]] = frozenset(
    {"evidence_sufficient", "no_evidence", "insufficient_evidence", "budget_spent"}
)
"""The closed set of stop reasons a terminal run may carry."""


@dataclass(frozen=True)
class RunContext:
    """One finished run and everything an invariant needs to judge it.

    Args:
        case: The case that produced the run, for its declared budget.
        state: The finished state, including its trace.
        corpus: The fixture the run retrieved from, for provenance checks.
        backend_name: The backend the runner bound, which every result must name.
    """

    case: EvalCase
    state: ResearchState
    corpus: Sequence[Document]
    backend_name: str

    @property
    def corpus_chunk_ids(self) -> frozenset[str]:
        """Return every chunk id the fixture can legitimately produce."""
        return frozenset(document.chunk_id for document in self.corpus)

    @property
    def corpus_source_paths(self) -> frozenset[str]:
        """Return every source path the fixture can legitimately produce."""
        return frozenset(document.source_path for document in self.corpus)


@dataclass(frozen=True)
class Invariant:
    """One property every run must have, and the check that proves it.

    Args:
        id: Stable slug reported in the scorecard.
        description: What the property is, in the terms an operator would use.
        check: Returns one message per way ``context`` violates the property.
    """

    id: str
    description: str
    check: Callable[[RunContext], Sequence[str]]


def _markers_in(report: str) -> list[int]:
    """Return the citation markers printed in a report, in printed order."""
    return [int(match) for match in MARKER.findall(report)]


def _budget_respected(context: RunContext) -> list[str]:
    """The run spent no more steps than it was given, and says so consistently."""
    state, case = context.state, context.case
    problems: list[str] = []
    if state.steps_taken > case.max_steps:
        problems.append(f"spent {state.steps_taken} step(s) against a budget of {case.max_steps}")
    if state.max_steps != case.max_steps:
        problems.append(f"carries max_steps {state.max_steps}, was given {case.max_steps}")
    stop = state.trace[-1] if state.trace else None
    if stop is not None and stop.event == "stop":
        if stop.payload.get("steps_used") != state.steps_taken:
            problems.append(
                f"stop event reports {stop.payload.get('steps_used')!r} steps, "
                f"state holds {state.steps_taken}"
            )
        if stop.payload.get("max_steps") != case.max_steps:
            problems.append("stop event reports a budget the case did not set")
    return problems


def _terminal_outcome(context: RunContext) -> list[str]:
    """The run finished, with a status and a reason from the closed sets."""
    state = context.state
    problems: list[str] = []
    if not state.is_finished:
        problems.append(f"ended with non-terminal status {state.status.value!r}")
    if state.stop_reason is None:
        problems.append("finished without a stop reason")
    elif state.stop_reason not in STOP_REASONS:
        problems.append(f"stop reason {state.stop_reason!r} is outside the closed set")
    if state.report is None or not state.report.strip():
        problems.append("finished without a report")
    return problems


def _trace_contract(context: RunContext) -> list[str]:
    """The trace is a complete, ordered, self-consistent record of the run."""
    state = context.state
    events = [event.event for event in state.trace]
    problems: list[str] = []

    if not events:
        return ["recorded no trace at all"]
    unknown = sorted(set(events) - TRACE_EVENT_NAMES)
    if unknown:
        problems.append(f"trace carries events outside the closed set: {unknown}")
    if events[0] != "plan_created":
        problems.append(f"trace opens with {events[0]!r} rather than 'plan_created'")
    if events.count("plan_created") != 1:
        problems.append(f"trace records {events.count('plan_created')} plans")
    if events[-1] != "stop":
        problems.append(f"trace ends with {events[-1]!r} rather than 'stop'")
    if events.count("stop") != 1:
        problems.append(f"trace records {events.count('stop')} stop events")
    if events.count("synthesize") != 1:
        problems.append(f"trace records {events.count('synthesize')} synthesise events")

    calls = events.count("tool_call")
    results = events.count("tool_result")
    if calls != results:
        problems.append(f"{calls} tool call(s) produced {results} result(s)")
    if results != state.steps_taken:
        problems.append(f"{results} tool result(s) against {state.steps_taken} recorded step(s)")
    for index, name in enumerate(events):
        if name == "tool_result" and (index == 0 or events[index - 1] != "tool_call"):
            problems.append(f"a tool result at position {index} follows no tool call")

    stop = state.trace[-1]
    if stop.event == "stop":
        if stop.payload.get("status") != state.status.value:
            problems.append("stop event disagrees with the state's status")
        if stop.payload.get("reason") != state.stop_reason:
            problems.append("stop event disagrees with the state's stop reason")
    return problems


def _plan_precedes_tools(context: RunContext) -> list[str]:
    """A plan exists, is within the documented cap, and is recorded before any call."""
    state = context.state
    problems: list[str] = []
    if not state.plan:
        problems.append("finished with an empty plan")
    if len(state.plan) > SPEC_MAX_SUB_QUESTIONS:
        problems.append(
            f"planned {len(state.plan)} sub-questions, above the documented cap of "
            f"{SPEC_MAX_SUB_QUESTIONS}"
        )
    events = [event.event for event in state.trace]
    if (
        "tool_call" in events
        and "plan_created" in events
        and events.index("plan_created") > events.index("tool_call")
    ):
        problems.append("a tool ran before the plan was recorded")
    first_plan = state.trace[0].payload.get("sub_questions") if state.trace else None
    if first_plan is not None and list(first_plan) != list(state.plan):
        problems.append("the traced plan is not the plan the state carries")
    return problems


def _citations_resolve(context: RunContext) -> list[str]:
    """Every printed marker resolves to a passage the run actually retrieved."""
    state = context.state
    problems: list[str] = []
    report = state.report or ""
    printed = _markers_in(report)
    declared = [citation.marker for citation in state.citations]

    if printed != declared:
        problems.append(f"report prints markers {printed} against citations {declared}")
    if declared != list(range(1, len(declared) + 1)):
        problems.append(f"citation markers are not 1..n in order: {declared}")

    evidence_ids = state.evidence_ids
    for citation in state.citations:
        if citation.chunk_id is None:
            problems.append(f"citation [{citation.marker}] resolves to no chunk id")
            continue
        if citation.chunk_id not in evidence_ids:
            problems.append(
                f"citation [{citation.marker}] cites {citation.chunk_id!r}, which the run "
                "never retrieved"
            )
            continue
        passage = state.evidence[citation.marker - 1]
        if citation.chunk_id != passage.chunk_id:
            problems.append(
                f"citation [{citation.marker}] points at {citation.chunk_id!r} but marker order "
                f"puts {passage.chunk_id!r} there"
            )
        if citation.source_path != passage.source_path:
            problems.append(f"citation [{citation.marker}] reports a foreign source path")
        if not citation.snippet:
            problems.append(f"citation [{citation.marker}] carries no snippet to check")
    return problems


def _provenance_is_real(context: RunContext) -> list[str]:
    """Nothing cited comes from outside the corpus the run was given."""
    problems: list[str] = []
    for chunk_id in context.state.evidence_ids:
        if chunk_id not in context.corpus_chunk_ids:
            problems.append(f"evidence {chunk_id!r} is not a chunk of the corpus")
    for citation in context.state.citations:
        if citation.source_path not in context.corpus_source_paths:
            problems.append(
                f"citation [{citation.marker}] names source {citation.source_path!r}, which is "
                "not in the corpus"
            )
    return problems


def _evidence_deduplicated(context: RunContext) -> list[str]:
    """One chunk is stored once, however many steps returned it."""
    ids = list(context.state.evidence_ids)
    if len(ids) == len(set(ids)):
        return []
    repeated = sorted({chunk_id for chunk_id in ids if ids.count(chunk_id) > 1})
    return [f"evidence holds {repeated} more than once"]


def _cite_or_refuse(context: RunContext) -> list[str]:
    """An answer carries citations; a run that cites nothing refuses.

    The portfolio's merge blocker for any answer-producing path, checked here
    rather than assumed: an uncited claim is the failure this whole project is
    arranged to make impossible.
    """
    state = context.state
    problems: list[str] = []
    refused = state.status is ResearchStatus.REFUSED
    has_citations = bool(state.citations)

    if not refused and not has_citations:
        problems.append(
            f"status {state.status.value!r} presented a report with no citation at all"
        )
    if state.has_evidence != has_citations:
        problems.append(
            f"gathered {len(state.evidence)} passage(s) but printed {len(state.citations)} "
            "citation(s)"
        )
    if refused and state.report and "Refused" not in state.report:
        problems.append("a refusal does not say so in its report")
    return problems


def _backend_is_the_bound_one(context: RunContext) -> list[str]:
    """Every result was served by the backend the runner bound, and no other."""
    problems: list[str] = []
    for event in context.state.trace:
        if event.event != "tool_result":
            continue
        backend = event.payload.get("backend")
        if backend != context.backend_name:
            problems.append(
                f"a step was served by backend {backend!r}, not the bound "
                f"{context.backend_name!r}"
            )
    return problems


def _gaps_are_reported(context: RunContext) -> list[str]:
    """A run that named a gap prints it, so a thin answer cannot read as a complete one."""
    state = context.state
    report = state.report or ""
    return [
        f"gap {gap.kind!r} was recorded but never printed"
        for gap in state.gaps
        if gap.detail not in report
    ]


INVARIANTS: Final[tuple[Invariant, ...]] = (
    Invariant(
        id="budget_respected",
        description="Steps taken never exceed the budget the case set, and the trace agrees.",
        check=_budget_respected,
    ),
    Invariant(
        id="terminal_outcome",
        description="Every run ends terminal, with a closed-set reason and a report.",
        check=_terminal_outcome,
    ),
    Invariant(
        id="trace_contract",
        description="The trace opens with a plan, pairs calls with results, and ends with stop.",
        check=_trace_contract,
    ),
    Invariant(
        id="plan_precedes_tools",
        description="A capped, non-empty plan is recorded before any tool runs.",
        check=_plan_precedes_tools,
    ),
    Invariant(
        id="citations_resolve",
        description="Every printed marker resolves, in order, to a passage that was retrieved.",
        check=_citations_resolve,
    ),
    Invariant(
        id="provenance_is_real",
        description="No cited chunk id or source path comes from outside the corpus.",
        check=_provenance_is_real,
    ),
    Invariant(
        id="evidence_deduplicated",
        description="A chunk returned by two steps is stored, and cited, once.",
        check=_evidence_deduplicated,
    ),
    Invariant(
        id="cite_or_refuse",
        description="An answer carries citations; a run with no evidence refuses.",
        check=_cite_or_refuse,
    ),
    Invariant(
        id="backend_is_the_bound_one",
        description="Every retrieval was served by the backend the runner bound.",
        check=_backend_is_the_bound_one,
    ),
    Invariant(
        id="gaps_are_reported",
        description="Every gap the critic named appears in the report.",
        check=_gaps_are_reported,
    ),
)
"""Every per-case invariant, in the order a scorecard lists them."""

INVARIANT_IDS: Final[tuple[str, ...]] = tuple(invariant.id for invariant in INVARIANTS)
"""The invariant ids, for a caller that wants to assert the set has not shrunk."""

DATASET_INVARIANT_IDS: Final[tuple[str, ...]] = (
    "deterministic_output",
    "surface_form_invariance",
)
"""Invariants a single run cannot show: they compare runs against each other."""


def check_run(context: RunContext) -> dict[str, tuple[str, ...]]:
    """Run every per-case invariant and return the violations, keyed by invariant.

    Args:
        context: The finished run and what it is judged against.

    Returns:
        A mapping from invariant id to its violation messages. Invariants that
        held are absent, so an empty mapping means a clean run.
    """
    found: dict[str, tuple[str, ...]] = {}
    for invariant in INVARIANTS:
        problems = tuple(invariant.check(context))
        if problems:
            found[invariant.id] = problems
    return found
