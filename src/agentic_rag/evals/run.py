"""Command-line entry point for the deterministic research evaluation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from agentic_rag.evals.dataset import DEFAULT_DATASET, DatasetError
from agentic_rag.evals.runner import evaluate


def build_parser() -> argparse.ArgumentParser:
    """Create the evaluation CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Golden JSONL dataset (defaults to data/eval/golden_research.jsonl).",
    )
    parser.add_argument("--pretty", action="store_true", help="Indent the JSON scorecard.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the free evaluation and print one JSON scorecard."""
    arguments = build_parser().parse_args(argv)
    try:
        report = evaluate(arguments.dataset)
    except (DatasetError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2
    indent = 2 if arguments.pretty else None
    print(report.model_dump_json(indent=indent))
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
