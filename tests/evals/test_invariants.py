"""The hard gates, checked against runs built to break exactly one of them."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from broken_runners import (
    always_refuses,
    answers_without_citing,
    fabricates_citations,
    overruns_the_budget,
    prints_an_unresolvable_marker,
    skips_the_plan,
)

from agentic_rag.agent.state import ResearchState, ResearchStatus
from agentic_rag.agent.synthesizer import Synthesis
from agentic_rag.evals.dataset import DATASET_SCHEMA_VERSION, EvalCase
from agentic_rag.evals.invariants import (
    DATASET_INVARIANT_IDS,
    INVARIANT_IDS,
    INVARIANTS,
    RunContext,
    check_run,
)
from agentic_rag.evals.runner import build_fixture_tool, default_runner
from agentic_rag.tools.retrieve import DEFAULT_CORPUS, RetrieveTool

QUESTION = "What is reciprocal rank fusion?"


def make_case(**overrides: object) -> EvalCase:
    payload: dict[str, object] = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "id": "invariant-probe",
        "category": "single_source_answerable",
        "question": QUESTION,
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
    return EvalCase.model_validate(payload)


def violations(state: ResearchState, *, case: EvalCase | None = None) -> dict[str, tuple[str, ...]]:
    return check_run(
        RunContext(
            case=case or make_case(),
            state=state,
            corpus=DEFAULT_CORPUS,
            backend_name="fake",
        )
    )


def run_broken(
    runner: object, *, case: EvalCase | None = None
) -> dict[str, tuple[str, ...]]:
    subject = case or make_case()
    tool = build_fixture_tool()
    state = runner(subject.question, tool, subject.max_steps, subject.top_k)  # type: ignore[operator]
    return violations(state, case=subject)


def test_the_invariant_set_has_not_shrunk() -> None:
    """The gate list is asserted explicitly so a removal shows up as a test change."""
    assert INVARIANT_IDS == (
        "budget_respected",
        "terminal_outcome",
        "trace_contract",
        "plan_precedes_tools",
        "citations_resolve",
        "provenance_is_real",
        "evidence_deduplicated",
        "cite_or_refuse",
        "backend_is_the_bound_one",
        "gaps_are_reported",
    )
    assert DATASET_INVARIANT_IDS == ("deterministic_output", "surface_form_invariance")
    assert len({invariant.id for invariant in INVARIANTS}) == len(INVARIANTS)
    for invariant in INVARIANTS:
        assert invariant.description.endswith("."), invariant.id


def test_an_honest_run_violates_nothing() -> None:
    case = make_case()
    state = default_runner(case.question, build_fixture_tool(), case.max_steps, case.top_k)
    assert violations(state, case=case) == {}


@pytest.mark.parametrize(
    ("question", "max_steps", "top_k"),
    [
        ("What is reciprocal rank fusion?", 4, 5),
        ("Who won the 1994 world cup final?", 3, 5),
        ("How does chunking work?", 1, 1),
        ("What is a citation?", 5, 1),
    ],
)
def test_honest_runs_stay_clean_across_the_outcome_table(
    question: str, max_steps: int, top_k: int
) -> None:
    """Every terminal outcome, not only the answering one, must satisfy the gates."""
    state = default_runner(question, build_fixture_tool(), max_steps, top_k)
    case = make_case(
        id="outcome-probe",
        question=question,
        max_steps=max_steps,
        top_k=top_k,
        expected_terminal_status=state.status.value,
        expected_stop_reason=state.stop_reason,
        expected_min_citations=0,
        expected_max_citations=None,
        expected_source_paths=[],
        expected_chunk_ids=[],
        category="single_source_answerable"
        if state.status is ResearchStatus.DONE
        else "no_evidence_refusal",
    )
    assert violations(state, case=case) == {}


def test_overrunning_the_budget_is_caught() -> None:
    found = run_broken(overruns_the_budget)
    assert "budget_respected" in found


def test_fabricated_provenance_is_caught() -> None:
    found = run_broken(fabricates_citations)
    assert "provenance_is_real" in found
    assert "citations_resolve" in found


def test_an_unresolvable_marker_is_caught() -> None:
    found = run_broken(prints_an_unresolvable_marker)
    assert "citations_resolve" in found


def test_answering_without_citing_is_caught() -> None:
    found = run_broken(answers_without_citing)
    assert "cite_or_refuse" in found


def test_retrieving_before_planning_is_caught() -> None:
    found = run_broken(skips_the_plan)
    assert "plan_precedes_tools" in found
    assert "trace_contract" in found


def test_refusing_everything_passes_the_gates_and_that_is_the_point() -> None:
    """A loop that always refuses breaks no invariant.

    Recorded as a test rather than left implicit: the gates check that a run is
    well formed, not that it is useful, so refusing everything is structurally
    valid. Catching it is the expectation metrics' job, and
    ``test_negative_controls.py`` asserts they do. An invariant that also failed
    here would be an invariant that punished honest refusals.
    """
    found = run_broken(always_refuses)
    assert found == {}


def test_a_non_terminal_run_is_caught() -> None:
    state = ResearchState(question=QUESTION, max_steps=4)
    state.record_plan([QUESTION])
    found = violations(state)
    assert "terminal_outcome" in found
    assert "trace_contract" in found


def test_a_foreign_backend_is_caught() -> None:
    """A result naming another backend fails, even if everything else is clean."""
    case = make_case()
    state = default_runner(case.question, build_fixture_tool(), case.max_steps, case.top_k)
    found = check_run(
        RunContext(case=case, state=state, corpus=DEFAULT_CORPUS, backend_name="live-http")
    )
    assert "backend_is_the_bound_one" in found


def test_a_run_carrying_someone_elses_budget_is_caught() -> None:
    case = make_case(max_steps=4)
    state = default_runner(case.question, build_fixture_tool(), 2, case.top_k)
    assert "budget_respected" in violations(state, case=case)


def test_an_unreported_gap_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """A named gap that never reaches the report would let a thin answer read as full."""
    case = make_case(question="How does chunking work?", max_steps=1, top_k=1)
    state = default_runner(case.question, build_fixture_tool(), case.max_steps, case.top_k)
    assert state.gaps, "the fixture case must produce a gap for this test to mean anything"
    object.__setattr__(state, "report", "Status: partial.")
    assert "gaps_are_reported" in violations(state, case=case)


def test_evidence_stored_twice_is_caught() -> None:
    case = make_case()
    state = default_runner(case.question, build_fixture_tool(), case.max_steps, case.top_k)
    duplicated = list(state.evidence) + [state.evidence[0]]
    object.__setattr__(state, "evidence", duplicated)
    assert "evidence_deduplicated" in violations(state, case=case)


def test_every_invariant_returns_a_sequence_of_messages() -> None:
    """The contract each check honours: no exceptions, no bare booleans."""
    case = make_case()
    state = default_runner(case.question, build_fixture_tool(), case.max_steps, case.top_k)
    context = RunContext(case=case, state=state, corpus=DEFAULT_CORPUS, backend_name="fake")
    for invariant in INVARIANTS:
        result = invariant.check(context)
        assert isinstance(result, Sequence)
        assert not isinstance(result, str)
        assert all(isinstance(message, str) for message in result)


def test_a_refusal_that_does_not_say_so_is_caught() -> None:
    case = make_case(
        id="silent-refusal",
        category="no_evidence_refusal",
        question="Who won the 1994 world cup final?",
        expected_terminal_status="refused",
        expected_stop_reason="no_evidence",
        expected_min_citations=0,
        expected_max_citations=0,
        expected_source_paths=[],
        expected_chunk_ids=[],
    )
    state = ResearchState(question=case.question, max_steps=case.max_steps)
    state.record_plan([case.question])
    state.record_synthesis(Synthesis(report="Nothing to say.", citations=()))
    state.finish(ResearchStatus.REFUSED, "no_evidence")
    assert "cite_or_refuse" in violations(state, case=case)


def test_the_bound_tool_never_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRODUCTION_RAG_URL", "https://example.invalid/rag")
    tool = build_fixture_tool()
    assert isinstance(tool, RetrieveTool)
    assert tool.backend_name == "fake"
