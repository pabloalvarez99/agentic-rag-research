"""Offline evaluation of the research loop against a committed golden dataset.

The package is arranged around one split, and every module belongs to one side of
it:

* **Hard invariants** (:mod:`agentic_rag.evals.invariants`) are properties every
  run must have whatever question it was asked. They fail the evaluation.
* **Descriptive metrics** (:mod:`agentic_rag.evals.metrics`) count how often the
  loop met an expectation a person derived from the documented rules. They are
  read, not enforced.

Everything else supports those two: :mod:`~agentic_rag.evals.dataset` defines and
validates the golden file, :mod:`~agentic_rag.evals.runner` executes it,
:mod:`~agentic_rag.evals.results` writes the artifact,
:mod:`~agentic_rag.evals.baseline` provides the single-pass reference, and
:mod:`~agentic_rag.evals.render` projects the JSON into a scorecard a person reads.

Nothing here reads a credential or opens a socket: the retrieval fixture is
constructed explicitly rather than resolved from the environment.
"""

from __future__ import annotations

from agentic_rag.evals.baseline import BaselineResult, run_baseline
from agentic_rag.evals.dataset import (
    CASE_CATEGORIES,
    DATASET_SCHEMA_VERSION,
    DatasetError,
    DatasetInvalid,
    EvalCase,
    EvalDataset,
    load_dataset,
    read_cases,
    validate_dataset,
)
from agentic_rag.evals.invariants import (
    INVARIANTS,
    Invariant,
    RunContext,
    check_run,
)
from agentic_rag.evals.metrics import compute_metrics, compute_metrics_by_category
from agentic_rag.evals.render import render_markdown
from agentic_rag.evals.results import (
    RESULTS_SCHEMA_VERSION,
    VOLATILE_FIELDS,
    CaseResult,
    MetricValue,
    Scorecard,
    scorecard_payload,
)
from agentic_rag.evals.runner import (
    build_fixture_tool,
    build_scorecard,
    evaluate_case,
    evaluate_dataset,
    gate_failures,
)

__all__ = [
    "CASE_CATEGORIES",
    "DATASET_SCHEMA_VERSION",
    "INVARIANTS",
    "RESULTS_SCHEMA_VERSION",
    "VOLATILE_FIELDS",
    "BaselineResult",
    "CaseResult",
    "DatasetError",
    "DatasetInvalid",
    "EvalCase",
    "EvalDataset",
    "Invariant",
    "MetricValue",
    "RunContext",
    "Scorecard",
    "build_fixture_tool",
    "build_scorecard",
    "check_run",
    "compute_metrics",
    "compute_metrics_by_category",
    "evaluate_case",
    "evaluate_dataset",
    "gate_failures",
    "load_dataset",
    "read_cases",
    "render_markdown",
    "run_baseline",
    "scorecard_payload",
    "validate_dataset",
]
