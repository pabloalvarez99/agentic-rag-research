"""The evaluation entry point: ``python -m agentic_rag.evals.run``.

Offline by default and offline in every mode: the retrieval fixture is constructed
here rather than discovered from the environment, so no shell variable can turn an
evaluation into a billed one.

The exit code says exactly one thing — whether something is broken:

===== =========================================================================
``0`` The dataset was evaluated and every hard invariant held. Expectation
      mismatches, if any, are reported and do not fail the run.
``1`` A hard invariant was violated, or ``--strict`` was passed and a run did
      not meet a constraint its case declared.
``2`` Reserved by ``argparse`` for a malformed command line.
``3`` The dataset failed integrity validation. Nothing was evaluated: a
      scorecard over a broken dataset describes the dataset, not the system.
===== =========================================================================

Usage::

    python -m agentic_rag.evals.run --dataset data/eval/golden_research.jsonl --repeat 3
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from agentic_rag.evals.dataset import DatasetInvalid, load_dataset
from agentic_rag.evals.render import render_markdown
from agentic_rag.evals.results import scorecard_payload, write_json, write_text
from agentic_rag.evals.runner import build_scorecard, gate_failures, summary_lines

EXIT_OK = 0
"""Everything the run can prove, it proved."""

EXIT_BROKEN_INVARIANT = 1
"""A property that must hold for any question did not hold."""

EXIT_BAD_DATASET = 3
"""The dataset could not be validated, so nothing was evaluated."""

DEFAULT_OUT = Path("reports/evals/latest.json")
"""Where the machine-readable scorecard lands unless the caller says otherwise."""


def _relative(path: Path) -> str:
    """Return ``path`` relative to the working directory when it is inside it."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the evaluation runner.

    Returns:
        A parser whose defaults keep the run offline, deterministic and free.
    """
    parser = argparse.ArgumentParser(
        prog="python -m agentic_rag.evals.run",
        description=(
            "Evaluate the research loop against a golden dataset on the free path. "
            "Produces fixture-contract evidence, never a quality result."
        ),
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="JSONL dataset to evaluate.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Where to write the results JSON (default: {DEFAULT_OUT.as_posix()}).",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=None,
        help="Also render the Markdown scorecard from that same JSON.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help=(
            "Evaluate the whole dataset this many times and compare the case records. "
            "Anything above 1 turns determinism into a measurement."
        ),
    )
    parser.add_argument(
        "--reproducible",
        action="store_true",
        help=(
            "Write volatile fields as a fixed placeholder so two clean clones can diff "
            "the artifact byte for byte."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Also exit nonzero when a run did not meet a constraint its case declared. "
            "Off by default: a mismatch may mean the expectation is wrong."
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the dataset and exit without running the loop.",
    )
    parser.add_argument(
        "--minimum-cases",
        type=int,
        default=48,
        help=(
            "Floor on dataset size, checked so a dataset cannot be quietly shrunk to "
            "improve a score (default: 48)."
        ),
    )
    return parser


def _command_line(arguments: argparse.Namespace) -> str:
    """Return the command as a stable string, without absolute paths."""
    parts = [
        "python -m agentic_rag.evals.run",
        f"--dataset {_relative(arguments.dataset)}",
        f"--repeat {arguments.repeat}",
        f"--out {_relative(arguments.out)}",
    ]
    if arguments.markdown is not None:
        parts.append(f"--markdown {_relative(arguments.markdown)}")
    if arguments.reproducible:
        parts.append("--reproducible")
    if arguments.strict:
        parts.append("--strict")
    return " ".join(parts)


def main(argv: Sequence[str] | None = None) -> int:
    """Evaluate a dataset and write the scorecard.

    Args:
        argv: Command-line arguments, or None to read ``sys.argv``.

    Returns:
        One of the documented exit codes.
    """
    arguments = build_parser().parse_args(argv)

    try:
        dataset = load_dataset(
            Path(arguments.dataset),
            minimum_cases=arguments.minimum_cases,
        )
    except FileNotFoundError:
        print(f"dataset not found: {_relative(Path(arguments.dataset))}")
        return EXIT_BAD_DATASET
    except DatasetInvalid as invalid:
        print(f"dataset failed validation with {len(invalid.errors)} problem(s):")
        for error in invalid.errors:
            print(f"  {error.case_id or '<file>'}  {error.code}: {error.detail}")
        return EXIT_BAD_DATASET

    print(f"dataset ok: {dataset.case_count} cases  {dataset.sha256}")
    if arguments.validate_only:
        for category, count in dataset.counts_by_category().items():
            print(f"  {category}: {count}")
        return EXIT_OK

    scorecard = build_scorecard(
        dataset,
        repeats=arguments.repeat,
        command=_command_line(arguments),
        reproducible=arguments.reproducible,
    )
    payload = scorecard_payload(scorecard)
    write_json(Path(arguments.out), payload)
    print(f"wrote {_relative(Path(arguments.out))}")

    if arguments.markdown is not None:
        write_text(Path(arguments.markdown), render_markdown(payload))
        print(f"wrote {_relative(Path(arguments.markdown))}")

    for line in summary_lines(scorecard):
        print(line)

    mismatched = scorecard.mismatched_cases
    if mismatched:
        print(f"{len(mismatched)} case(s) did not meet a declared expectation:")
        for case in mismatched:
            unmet = [name for name, met in case.matches.model_dump().items() if met is False]
            print(f"  {case.id}: {', '.join(unmet)}")

    failures = gate_failures(scorecard, strict=arguments.strict)
    if failures:
        print("FAILED:")
        for reason in failures:
            print(f"  {reason}")
        return EXIT_BROKEN_INVARIANT
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised through the module CLI
    raise SystemExit(main())
