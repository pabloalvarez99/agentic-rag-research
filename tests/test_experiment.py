"""Experiment records built from finished free-path runs."""

from __future__ import annotations

from agentic_rag.agent import run_research
from agentic_rag.experiment import ExperimentRecord
from agentic_rag.tools import FakeRetrievalBackend, RetrieveTool


def test_experiment_record_from_state_carries_note_ids_and_stop_reason() -> None:
    state = run_research(
        "How does reciprocal rank fusion score a document?",
        tool=RetrieveTool(FakeRetrievalBackend()),
        max_steps=4,
    )
    record = ExperimentRecord.from_state(state, experiment_id="exp-test-1", seed=0)

    assert record.id == "exp-test-1"
    assert record.seed == 0
    assert record.stop_reason == state.stop_reason
    assert record.status == state.status.value
    assert record.budget.max_steps == 4
    assert "retrieve" in record.budget.max_calls
    assert record.note_ids == state.note_ids
    assert record.pack_hash is None
    assert record.tool_calls.get("retrieve", 0) >= 1
    assert record.trace_event_count == len(state.trace)
