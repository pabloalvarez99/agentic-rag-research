"""The command line: exit codes that mean something, and files that land."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from broken_runners import fabricates_citations

from agentic_rag.evals import render, run
from agentic_rag.evals.dataset import load_dataset
from agentic_rag.evals.results import scorecard_payload, write_json
from agentic_rag.evals.runner import build_scorecard

DATASET = "data/eval/golden_research.jsonl"


def test_a_clean_evaluation_exits_zero(tmp_path: Path) -> None:
    out = tmp_path / "latest.json"
    code = run.main(["--dataset", DATASET, "--out", str(out), "--repeat", "2"])
    assert code == run.EXIT_OK
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["determinism"]["stable"] is True
    assert payload["dataset"]["case_count"] >= 48


def test_the_markdown_is_rendered_from_the_same_json(tmp_path: Path) -> None:
    out = tmp_path / "latest.json"
    markdown = tmp_path / "latest.md"
    assert run.main(
        ["--dataset", DATASET, "--out", str(out), "--markdown", str(markdown)]
    ) == run.EXIT_OK
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert markdown.read_text(encoding="utf-8") == render.render_markdown(payload)


def test_a_missing_dataset_exits_three(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    absent = tmp_path / "absent.jsonl"
    code = run.main(["--dataset", str(absent), "--out", str(tmp_path / "out.json")])
    assert code == run.EXIT_BAD_DATASET
    assert "dataset not found" in capsys.readouterr().out


def test_a_broken_dataset_exits_three_and_evaluates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A scorecard over a broken dataset would describe the dataset, not the system."""
    broken = tmp_path / "broken.jsonl"
    broken.write_text('{"id": "no-schema-version"}\n', encoding="utf-8")
    out = tmp_path / "latest.json"
    assert run.main(["--dataset", str(broken), "--out", str(out)]) == run.EXIT_BAD_DATASET
    assert "failed validation" in capsys.readouterr().out
    assert not out.exists()


def test_the_size_floor_cannot_be_lowered_into_passing(tmp_path: Path) -> None:
    """``--minimum-cases`` exists, and raising it past the dataset still fails."""
    out = tmp_path / "latest.json"
    assert run.main(
        ["--dataset", DATASET, "--out", str(out), "--minimum-cases", "500"]
    ) == run.EXIT_BAD_DATASET


def test_validate_only_checks_the_file_without_running_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "latest.json"
    assert run.main(["--dataset", DATASET, "--out", str(out), "--validate-only"]) == run.EXIT_OK
    assert not out.exists()
    printed = capsys.readouterr().out
    assert "dataset ok" in printed
    assert "duplicate_evidence" in printed


def test_a_violated_invariant_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate is proven to bite by running the CLI over a broken implementation."""
    monkeypatch.setattr(run, "build_scorecard", _with_runner(fabricates_citations))
    out = tmp_path / "latest.json"
    code = run.main(["--dataset", DATASET, "--out", str(out)])
    assert code == run.EXIT_BROKEN_INVARIANT
    printed = capsys.readouterr().out
    assert "FAILED:" in printed
    assert "citations_resolve" in printed
    assert out.exists(), "a failing run still writes its evidence"


def test_a_malformed_command_line_exits_two() -> None:
    with pytest.raises(SystemExit) as raised:
        run.main(["--repeat", "3"])
    assert raised.value.code == 2


def _with_runner(runner: object) -> object:
    """Return a ``build_scorecard`` bound to a chosen implementation."""

    def build(dataset: object, **kwargs: object) -> object:
        kwargs["runner"] = runner
        return build_scorecard(dataset, **kwargs)  # type: ignore[arg-type]

    return build


def test_the_recorded_command_carries_no_absolute_path(tmp_path: Path) -> None:
    out = tmp_path / "latest.json"
    run.main(["--dataset", DATASET, "--out", str(out), "--repeat", "1", "--reproducible"])
    payload = json.loads(out.read_text(encoding="utf-8"))
    command = payload["run"]["command"]
    assert command.startswith("python -m agentic_rag.evals.run")
    assert ":" not in command.replace("C:", "")  # a drive letter is the only colon possible
    assert "--reproducible" in command


def test_the_renderer_runs_standalone(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dataset = load_dataset(DATASET)
    payload = scorecard_payload(build_scorecard(dataset, repeats=1))
    results = tmp_path / "results.json"
    write_json(results, payload)

    markdown = tmp_path / "scorecard.md"
    assert render.main(["--results", str(results), "--out", str(markdown)]) == 0
    assert markdown.read_text(encoding="utf-8").startswith("# Agentic research loop")

    assert render.main(["--results", str(results)]) == 0
    assert "## Hard invariants" in capsys.readouterr().out
