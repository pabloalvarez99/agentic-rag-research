"""The invariants of a run, checked against the run itself.

Every claim the loop makes is checkable from the state it returns, and this is
where the checking happens. It exists because the loop's tests assert what one
scenario produced, and that is not the same as asserting what any run must
satisfy — a bug that only shows up on the eleventh adversarial input is a bug no
scenario test was ever going to name.

Two properties make it worth having rather than inlining the assertions:

* **It is pure.** It reads a :class:`~agentic_rag.agent.state.ResearchState` and
  returns a report. It sets no field, appends no event, and holds no reference a
  caller could write through. A verifier that repairs what it finds is a verifier
  that hides how often it is needed.
* **It does not trust the values.** Every check is written against a trace that
  may have been built by something other than the loop — reordered, truncated,
  or constructed field by field. That is the only way it can be evidence about a
  run rather than a restatement of the code that produced it. What it does trust
  is that the fields hold the *types* they declare, which is pydantic's job at
  the boundary the state was validated at; re-checking that here would double
  every branch to catch a corruption no serialisation round-trip can produce.

The checks are grouped by what they read, and each returns its own violations, so
a corrupted run reports every problem it has instead of the first one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Final, get_args

from agentic_rag.agent.state import (
    ResearchState,
    ResearchStatus,
    TraceEvent,
    TraceEventName,
)
from agentic_rag.verification.report import VerificationReport, Violation

TRACE_EVENT_NAMES: Final[frozenset[str]] = frozenset(get_args(TraceEventName))
"""Names a trace event may carry, taken from the declaration rather than retyped."""

MARKER: Final = re.compile(r"\[(\d+)\]")
"""A citation marker as the synthesiser prints it."""

_START: Final = "start"
_STOPPED: Final = "stopped"

_GRAMMAR: Final[dict[str, dict[str, str]]] = {
    _START: {"plan_created": "planned"},
    "planned": {"tool_call": "called", "synthesize": "synthesised"},
    "called": {"tool_result": "retrieved", "tool_error": "failed"},
    "retrieved": {"critique": "planned"},
    "failed": {"synthesize": "synthesised"},
    "synthesised": {"stop": _STOPPED},
    _STOPPED: {},
}
"""The loop's control flow as the events it leaves behind.

``plan_created (tool_call (tool_result critique | tool_error))* synthesize stop``.
A failed call leads to ``synthesize`` and nowhere else: the run stops at the
first failure, so a trace that retried would not be a trace this loop produced.
"""

_STATUS_REASONS: Final[dict[ResearchStatus, frozenset[str]]] = {
    ResearchStatus.DONE: frozenset({"evidence_sufficient"}),
    ResearchStatus.REFUSED: frozenset({"no_evidence", "insufficient_evidence"}),
    ResearchStatus.BUDGET_EXHAUSTED: frozenset({"budget_spent"}),
    ResearchStatus.DEGRADED: frozenset({"tool_failed"}),
}
"""Which reasons each terminal status may carry. Any other pair is a contradiction."""

_TOOL_OUTCOMES: Final[frozenset[str]] = frozenset({"tool_result", "tool_error"})


def _indices(trace: Sequence[TraceEvent], name: str) -> list[int]:
    """Return the positions of every event called ``name``."""
    return [index for index, event in enumerate(trace) if event.event == name]


def _check_event_names(trace: Sequence[TraceEvent]) -> list[Violation]:
    """Every event carries one of the declared names."""
    return [
        Violation(
            code="unknown_event",
            detail=f"event {event.event!r} is not one of the declared trace events",
            event_index=index,
        )
        for index, event in enumerate(trace)
        if event.event not in TRACE_EVENT_NAMES
    ]


def _check_grammar(trace: Sequence[TraceEvent]) -> list[Violation]:
    """Events follow the loop's control flow.

    Reports the first event that could not follow the ones before it and stops:
    once the trace has left the grammar, every later complaint is about a state
    machine that is already lost, and a reader would have to guess which
    violation was the real one.
    """
    state = _START
    for index, event in enumerate(trace):
        allowed = _GRAMMAR[state]
        if event.event not in allowed:
            expected = ", ".join(sorted(allowed)) or "nothing"
            return [
                Violation(
                    code="event_out_of_order",
                    detail=(
                        f"{event.event!r} cannot follow {state!r}; "
                        f"the loop can only record {expected} there"
                    ),
                    event_index=index,
                )
            ]
        state = allowed[event.event]
    return []


def _check_plan(state: ResearchState) -> list[Violation]:
    """The run planned before it did anything, and the plan is not empty."""
    planned = _indices(state.trace, "plan_created")
    if not planned:
        return [Violation(code="plan_missing", detail="the run recorded no plan_created event")]
    violations = [
        Violation(
            code="plan_missing",
            detail="plan_created was recorded more than once",
            event_index=index,
        )
        for index in planned[1:]
    ]
    if planned[0] != 0:
        violations.append(
            Violation(
                code="plan_missing",
                detail="the run recorded work before it recorded a plan",
                event_index=planned[0],
            )
        )
    if not state.plan:
        violations.append(
            Violation(code="plan_missing", detail="the run carries an empty plan")
        )
    return violations


def _check_pairing(trace: Sequence[TraceEvent]) -> list[Violation]:
    """Every tool call is answered exactly once, by a result or by an error."""
    violations: list[Violation] = []
    open_call: int | None = None
    for index, event in enumerate(trace):
        if event.event == "tool_call":
            if open_call is not None:
                violations.append(
                    Violation(
                        code="tool_call_unresolved",
                        detail="a tool_call was followed by another before it was answered",
                        event_index=open_call,
                    )
                )
            open_call = index
        elif event.event in _TOOL_OUTCOMES:
            if open_call is None:
                violations.append(
                    Violation(
                        code="tool_outcome_unpaired",
                        detail=f"{event.event} answers no tool_call",
                        event_index=index,
                    )
                )
            open_call = None
    if open_call is not None:
        violations.append(
            Violation(
                code="tool_call_unresolved",
                detail="a tool_call was never answered by a result or an error",
                event_index=open_call,
            )
        )
    return violations


def _check_stop(state: ResearchState) -> list[Violation]:
    """A finished run stopped exactly once, and stopping was the last thing it did."""
    stops = _indices(state.trace, "stop")
    violations: list[Violation] = []
    if state.is_finished and not stops:
        violations.append(
            Violation(
                code="stop_missing",
                detail=f"status is {state.status.value!r} but no stop event was recorded",
            )
        )
    violations.extend(
        Violation(
            code="stop_repeated",
            detail="the run recorded a second stop event",
            event_index=index,
        )
        for index in stops[1:]
    )
    if stops and stops[0] != len(state.trace) - 1:
        violations.append(
            Violation(
                code="stop_not_last",
                detail=f"{len(state.trace) - 1 - stops[0]} event(s) were recorded after stop",
                event_index=stops[0],
            )
        )
    if stops and not state.is_finished:
        violations.append(
            Violation(
                code="status_not_terminal",
                detail="the run recorded a stop event but its status is still running",
                event_index=stops[0],
            )
        )
    return violations


def _check_status(state: ResearchState) -> list[Violation]:
    """Status and stop reason are a pair the policy can produce."""
    if not state.is_finished:
        if state.stop_reason is not None:
            return [
                Violation(
                    code="status_reason_mismatch",
                    detail=f"a running run carries the stop reason {state.stop_reason!r}",
                )
            ]
        return []
    allowed = _STATUS_REASONS[state.status]
    if state.stop_reason not in allowed:
        return [
            Violation(
                code="status_reason_mismatch",
                detail=(
                    f"status {state.status.value!r} cannot carry the reason "
                    f"{state.stop_reason!r}; it takes one of {', '.join(sorted(allowed))}"
                ),
            )
        ]
    return []


def _check_budget(state: ResearchState) -> list[Violation]:
    """No run takes more steps than it was given, and a failed step is a step."""
    violations: list[Violation] = []
    if state.steps_taken > state.max_steps:
        violations.append(
            Violation(
                code="budget_exceeded",
                detail=f"{state.steps_taken} step(s) were taken on a budget of {state.max_steps}",
            )
        )
    attempted = sum(1 for event in state.trace if event.event in _TOOL_OUTCOMES)
    if attempted > state.max_steps:
        violations.append(
            Violation(
                code="budget_exceeded",
                detail=(
                    f"the trace records {attempted} answered tool call(s) "
                    f"on a budget of {state.max_steps}"
                ),
            )
        )
    return violations


def _check_synthesis(state: ResearchState) -> list[Violation]:
    """A finished run composed a report before it stopped, and kept it."""
    if not state.is_finished:
        return []
    violations: list[Violation] = []
    synthesised = _indices(state.trace, "synthesize")
    stops = _indices(state.trace, "stop")
    if not synthesised:
        violations.append(
            Violation(code="synthesis_missing", detail="the run stopped without synthesising")
        )
    elif stops and synthesised[0] > stops[0]:
        violations.append(
            Violation(
                code="synthesis_missing",
                detail="the run synthesised after it had already stopped",
                event_index=synthesised[0],
            )
        )
    if not state.report:
        violations.append(
            Violation(code="report_missing", detail="a finished run carries no report")
        )
    return violations


def _check_citations(state: ResearchState) -> list[Violation]:
    """Markers resolve, citations are printed, and each one names evidence the run has."""
    violations: list[Violation] = []
    markers = [int(found) for found in MARKER.findall(state.report or "")]
    cited = [citation.marker for citation in state.citations]

    for marker in sorted(set(markers) - set(cited)):
        violations.append(
            Violation(
                code="citation_marker_unresolved",
                detail=f"the report prints [{marker}], which resolves to no citation",
            )
        )
    for marker in sorted(set(cited) - set(markers)):
        violations.append(
            Violation(
                code="citation_unprinted",
                detail=f"citation [{marker}] is never printed in the report",
            )
        )
    if cited != list(range(1, len(cited) + 1)):
        violations.append(
            Violation(
                code="citation_out_of_order",
                detail=f"citation markers are {cited}, not 1..{len(cited)} in order",
            )
        )

    evidence = {passage.chunk_id: passage for passage in state.evidence}
    for citation in state.citations:
        passage = evidence.get(citation.chunk_id or "")
        if passage is None:
            violations.append(
                Violation(
                    code="citation_not_grounded",
                    detail=(
                        f"citation [{citation.marker}] names chunk "
                        f"{citation.chunk_id!r}, which this run never retrieved"
                    ),
                )
            )
            continue
        if citation.source_path != passage.source_path:
            violations.append(
                Violation(
                    code="citation_not_grounded",
                    detail=(
                        f"citation [{citation.marker}] points at {citation.source_path!r} "
                        f"but chunk {passage.chunk_id!r} came from {passage.source_path!r}"
                    ),
                )
            )
        if not _snippet_of(citation.snippet, passage.text):
            violations.append(
                Violation(
                    code="citation_not_grounded",
                    detail=(
                        f"citation [{citation.marker}] quotes text that is not in chunk "
                        f"{passage.chunk_id!r}"
                    ),
                )
            )
    return violations


def _snippet_of(snippet: str | None, text: str) -> bool:
    """Return whether ``snippet`` is a printable quotation of ``text``.

    The printed form of a passage is not its text: whitespace is collapsed,
    control characters are replaced, a long passage is cut at a word boundary,
    and a marker shape is neutralised. So the check is on the words, and on the
    part that survived the cut — enough to catch a snippet swapped for another
    passage's, or edited after the fact, without re-implementing the synthesiser.
    """
    if snippet is None:
        return True
    head = snippet.removesuffix("...").removesuffix(".").strip()
    if not head:
        return False
    return _words(head) <= _words(text)


def _words(text: str) -> set[str]:
    """Return the alphanumeric words of ``text``, lowercased."""
    return set(re.findall(r"[0-9a-z]+", text.lower()))


def _check_evidence(state: ResearchState) -> list[Violation]:
    """Evidence holds each chunk once."""
    seen: set[str] = set()
    violations: list[Violation] = []
    for passage in state.evidence:
        if passage.chunk_id in seen:
            violations.append(
                Violation(
                    code="evidence_duplicated",
                    detail=f"chunk {passage.chunk_id!r} is held twice in the evidence",
                )
            )
        seen.add(passage.chunk_id)
    return violations


def _check_trace_state(state: ResearchState) -> list[Violation]:
    """The trace and the state tell the same story.

    They are two records of one run, written at the same moments by the same
    methods. Anything that made them disagree — a hand-built state, an event
    edited after the fact, evidence added without a step — is exactly what a
    verifier is for.
    """
    violations: list[Violation] = []
    trace = state.trace

    for index in _indices(trace, "plan_created"):
        recorded = trace[index].payload.get("sub_questions")
        if recorded != state.plan:
            violations.append(
                Violation(
                    code="trace_state_mismatch",
                    detail="plan_created does not carry the plan the run holds",
                    event_index=index,
                )
            )

    attempts = [index for index, event in enumerate(trace) if event.event in _TOOL_OUTCOMES]
    if len(attempts) != state.steps_taken:
        violations.append(
            Violation(
                code="trace_state_mismatch",
                detail=(
                    f"the trace records {len(attempts)} answered tool call(s) "
                    f"but the run holds {state.steps_taken} step(s)"
                ),
            )
        )
    else:
        violations.extend(_check_steps_against_trace(state, attempts))

    violations.extend(_check_evidence_against_trace(state, attempts))
    violations.extend(_check_critique_against_trace(state))
    violations.extend(_check_synthesis_against_trace(state))
    violations.extend(_check_stop_against_trace(state))
    return violations


def _check_steps_against_trace(state: ResearchState, attempts: Sequence[int]) -> list[Violation]:
    """Each recorded step matches the event that answered its call."""
    violations: list[Violation] = []
    for step, index in zip(state.steps, attempts, strict=True):
        event = state.trace[index]
        payload = event.payload
        if payload.get("question") != step.request:
            violations.append(
                Violation(
                    code="trace_state_mismatch",
                    detail=f"{event.event} names a sub-question the step does not",
                    event_index=index,
                )
            )
        if step.failed and event.event != "tool_error":
            violations.append(
                Violation(
                    code="trace_state_mismatch",
                    detail="a failed step is traced as a completed one",
                    event_index=index,
                )
            )
        if not step.failed and event.event != "tool_result":
            violations.append(
                Violation(
                    code="trace_state_mismatch",
                    detail="a completed step is traced as a failure",
                    event_index=index,
                )
            )
        if event.event == "tool_result" and payload.get("evidence_ids") != list(step.evidence_ids):
            violations.append(
                Violation(
                    code="trace_state_mismatch",
                    detail="tool_result names evidence the step does not",
                    event_index=index,
                )
            )
        if step.failure is not None and payload.get("detail") != step.failure.detail:
            violations.append(
                Violation(
                    code="trace_state_mismatch",
                    detail="tool_error does not carry the failure the step holds",
                    event_index=index,
                )
            )
    return violations


def _check_evidence_against_trace(state: ResearchState, attempts: Iterable[int]) -> list[Violation]:
    """Every passage the run holds arrived through a traced retrieval."""
    retrieved: set[str] = set()
    for index in attempts:
        event = state.trace[index]
        if event.event != "tool_result":
            continue
        ids = event.payload.get("evidence_ids")
        if isinstance(ids, list):
            retrieved.update(str(chunk_id) for chunk_id in ids)

    held = set(state.evidence_ids)
    ungrounded = sorted(held - retrieved)
    if ungrounded:
        return [
            Violation(
                code="trace_state_mismatch",
                detail=f"evidence {ungrounded} is held but no tool_result returned it",
            )
        ]
    return []


def _check_critique_against_trace(state: ResearchState) -> list[Violation]:
    """The gaps the run holds are the ones its last critique named."""
    critiques = _indices(state.trace, "critique")
    if not critiques:
        return []
    payload = state.trace[critiques[-1]].payload
    if payload.get("gaps") != [gap.detail for gap in state.gaps]:
        return [
            Violation(
                code="trace_state_mismatch",
                detail="the run's gaps are not the ones its last critique recorded",
                event_index=critiques[-1],
            )
        ]
    return []


def _check_synthesis_against_trace(state: ResearchState) -> list[Violation]:
    """The synthesis event agrees with the citations the run kept."""
    violations: list[Violation] = []
    for index in _indices(state.trace, "synthesize"):
        payload = state.trace[index].payload
        if payload.get("citation_markers") != [citation.marker for citation in state.citations]:
            violations.append(
                Violation(
                    code="trace_state_mismatch",
                    detail="synthesize names markers the run's citations do not",
                    event_index=index,
                )
            )
        if payload.get("evidence_available") != len(state.evidence):
            violations.append(
                Violation(
                    code="trace_state_mismatch",
                    detail="synthesize counts evidence the run does not hold",
                    event_index=index,
                )
            )
    return violations


def _check_stop_against_trace(state: ResearchState) -> list[Violation]:
    """The stop event agrees with the outcome the run carries."""
    violations: list[Violation] = []
    for index in _indices(state.trace, "stop"):
        payload = state.trace[index].payload
        expected: dict[str, object] = {
            "status": state.status.value,
            "reason": state.stop_reason,
            "steps_used": state.steps_taken,
            "max_steps": state.max_steps,
        }
        wrong = sorted(key for key, value in expected.items() if payload.get(key) != value)
        if wrong:
            violations.append(
                Violation(
                    code="trace_state_mismatch",
                    detail=f"stop disagrees with the run about: {', '.join(wrong)}",
                    event_index=index,
                )
            )
    return violations


def verify_run(state: ResearchState) -> VerificationReport:
    """Check one run against every invariant and return what does not hold.

    Reads only. The state it is given is the state it gives back to its caller,
    field for field, whatever it finds.

    Args:
        state: A run, finished or not, built by the loop or by anything else.

    Returns:
        A report whose :attr:`~agentic_rag.verification.report.VerificationReport.ok`
        is true exactly when the run holds the whole contract.
    """
    violations: list[Violation] = [
        *_check_event_names(state.trace),
        *_check_grammar(state.trace),
        *_check_plan(state),
        *_check_pairing(state.trace),
        *_check_stop(state),
        *_check_status(state),
        *_check_budget(state),
        *_check_synthesis(state),
        *_check_citations(state),
        *_check_evidence(state),
        *_check_trace_state(state),
    ]
    return VerificationReport(violations=tuple(violations))


def stop_reasons_for(status: ResearchStatus) -> frozenset[str]:
    """Return the stop reasons ``status`` may be recorded with.

    Exposed so a caller can read the compatibility table instead of duplicating
    it. The values are members of :data:`~agentic_rag.agent.state.StopReason`.
    """
    return _STATUS_REASONS.get(status, frozenset())


__all__ = ["MARKER", "TRACE_EVENT_NAMES", "stop_reasons_for", "verify_run"]
