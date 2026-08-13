"""The offline guarantee, tested rather than asserted.

"It does not use the network" is the kind of claim that stays true until someone
adds a convenience. These tests make the claim mechanical: sockets are poisoned,
the HTTP client is poisoned, and the environment variable that would redirect
retrieval to a live service is set to something that would fail loudly if anything
read it.

Also here: the baseline, whose whole risk is being quoted as a quality comparison.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, NoReturn

import httpx
import pytest

from agentic_rag.evals.baseline import BASELINE_LABEL, run_baseline
from agentic_rag.evals.dataset import load_dataset
from agentic_rag.evals.run import main as run_main
from agentic_rag.evals.runner import build_fixture_tool, build_scorecard

DATASET = "data/eval/golden_research.jsonl"


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any attempt to reach the network raise, loudly and immediately."""

    def refuse(*args: Any, **kwargs: Any) -> NoReturn:
        raise AssertionError("the evaluation attempted to use the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(httpx, "Client", refuse)
    monkeypatch.setattr(httpx, "AsyncClient", refuse)


def test_a_full_evaluation_runs_with_the_network_poisoned(
    tmp_path: Path, no_network: None
) -> None:
    out = tmp_path / "latest.json"
    assert run_main(["--dataset", DATASET, "--out", str(out), "--repeat", "2"]) == 0
    assert out.exists()


def test_the_production_url_is_never_read(
    tmp_path: Path, no_network: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shell variable must not be able to turn an evaluation into a billed one."""
    out = tmp_path / "latest.json"
    command = ["--dataset", DATASET, "--out", str(out), "--reproducible"]

    monkeypatch.setenv("PRODUCTION_RAG_URL", "https://example.invalid/rag")
    assert run_main(command) == 0
    with_variable = out.read_bytes()

    monkeypatch.delenv("PRODUCTION_RAG_URL")
    assert run_main(command) == 0

    assert out.read_bytes() == with_variable


def test_the_scorecard_records_the_backend_that_actually_served_every_step() -> None:
    """The offline claim is auditable from the artifact, not only from the code."""
    scorecard = build_scorecard(load_dataset(DATASET), repeats=1)
    assert scorecard.run.backend == "fake"
    assert scorecard.run.network_used is False
    assert scorecard.run.billed_usd == 0.0
    for case in scorecard.cases:
        if case.observed.steps_used:
            assert case.observed.backends == ("fake",)


def test_no_test_here_depends_on_a_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clearing every plausible credential must change nothing."""
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "PRODUCTION_RAG_URL",
        "COHERE_API_KEY",
        "HF_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    scorecard = build_scorecard(load_dataset(DATASET), repeats=1)
    assert scorecard.failed_invariants == ()


def test_the_baseline_is_one_pass_over_the_same_fixture() -> None:
    result = run_baseline(build_fixture_tool(), "What is reciprocal rank fusion?", top_k=5)
    assert result.backend == "fake"
    assert result.label == BASELINE_LABEL
    assert "control-flow reference only" in result.label


def test_the_baseline_counts_distinct_passages() -> None:
    result = run_baseline(build_fixture_tool(), "Who won the 1994 world cup final?", top_k=5)
    assert result.evidence_ids == ()
    assert result.evidence_count == 0


def test_the_baseline_never_produces_an_answer() -> None:
    """Nothing in the reference can be read as an answer, because it makes none."""
    result = run_baseline(build_fixture_tool(), "How does chunking work?", top_k=5)
    fields = set(type(result).model_fields)
    assert fields == {"label", "evidence_ids", "source_paths", "backend"}
