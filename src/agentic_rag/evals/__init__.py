"""Offline evaluation of the bounded research loop."""

from agentic_rag.evals.dataset import DEFAULT_DATASET, load_dataset
from agentic_rag.evals.models import CaseResult, EvalMetrics, EvalReport, GoldenCase
from agentic_rag.evals.runner import evaluate, evaluate_case

__all__ = [
    "DEFAULT_DATASET",
    "CaseResult",
    "EvalMetrics",
    "EvalReport",
    "GoldenCase",
    "evaluate",
    "evaluate_case",
    "load_dataset",
]
