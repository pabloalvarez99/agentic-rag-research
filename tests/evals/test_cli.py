"""The evaluation module emits a machine-readable scorecard."""

from __future__ import annotations

import json

import pytest

from agentic_rag.evals.run import main


def test_cli_prints_json_and_returns_success(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["provider"] == "fake"
    assert payload["billed_usd"] == 0.0
    assert payload["metrics"]["passed_cases"] == payload["metrics"]["total_cases"]
    assert payload["metrics"]["total_cases"] >= 40
