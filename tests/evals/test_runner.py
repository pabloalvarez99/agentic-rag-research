"""Behavioral metrics over the deterministic research loop."""

from __future__ import annotations

import json

import pytest

from agentic_rag.evals import evaluate


def test_every_committed_golden_passes_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCTION_RAG_URL", "http://127.0.0.1:9")

    report = evaluate()

    assert report.all_passed
    assert report.provider == "fake"
    assert report.billed_usd == 0.0
    assert report.metrics.total_cases == 18
    assert report.metrics.passed_cases == 18
    assert report.metrics.status_counts == {"budget_exhausted": 3, "done": 7, "refused": 8}
    assert 1.0 <= report.metrics.mean_steps_used <= 2.0
    assert 0.0 < report.metrics.has_citations_rate < 1.0
    assert report.metrics.citation_present_rate == report.metrics.has_citations_rate
    assert report.metrics.stop_reason_counts
    assert sum(report.metrics.stop_reason_counts.values()) == 18
    assert report.metrics.unanswerable_cases == 4
    assert report.metrics.refused_unanswerable == 4
    assert report.metrics.refused_unanswerable_rate == 1.0
    # Control scorecard: never a quality ranking against another system.
    dumped = report.model_dump()
    assert "beats" not in json.dumps(dumped).lower()
    assert "gpt" not in json.dumps(dumped).lower()
