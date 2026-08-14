"""Strict JSONL loading and integrity checks for research goldens."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from agentic_rag.evals.models import GoldenCase
from agentic_rag.tools import DEFAULT_CORPUS

DEFAULT_DATASET: Final = (
    Path(__file__).resolve().parents[3] / "data" / "eval" / "golden_research.jsonl"
)
REQUIRED_CATEGORIES: Final = frozenset(
    {"answerable_multi_hop", "unanswerable", "budget_stress"}
)


class DatasetError(ValueError):
    """The golden dataset is malformed or internally inconsistent."""


def load_dataset(path: Path = DEFAULT_DATASET) -> tuple[GoldenCase, ...]:
    """Load and validate every non-empty JSONL record from ``path``."""
    cases: list[GoldenCase] = []
    seen_ids: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            document = json.loads(raw)
            case = GoldenCase.model_validate(document)
        except (json.JSONDecodeError, ValidationError) as error:
            raise DatasetError(f"{path}:{line_number}: invalid golden case: {error}") from error
        if case.id in seen_ids:
            raise DatasetError(f"{path}:{line_number}: duplicate id {case.id!r}")
        seen_ids.add(case.id)
        cases.append(case)

    if not cases:
        raise DatasetError(f"{path}: dataset is empty")
    _validate_integrity(cases, path)
    return tuple(cases)


def _validate_integrity(cases: list[GoldenCase], path: Path) -> None:
    """Check cross-record invariants that Pydantic cannot express."""
    categories = {case.category for case in cases}
    missing = REQUIRED_CATEGORIES - categories
    if missing:
        raise DatasetError(f"{path}: missing required categories: {sorted(missing)}")

    corpus_ids = {document.chunk_id for document in DEFAULT_CORPUS}
    unknown_ids = {
        chunk_id
        for case in cases
        for chunk_id in case.expect.cite_chunk_ids_any
        if chunk_id not in corpus_ids
    }
    if unknown_ids:
        raise DatasetError(
            f"{path}: expected chunk ids are not in the fake corpus: {sorted(unknown_ids)}"
        )

    pairs: dict[str, list[GoldenCase]] = {}
    for case in cases:
        if case.pair_id is not None:
            pairs.setdefault(case.pair_id, []).append(case)
    for pair_id, members in pairs.items():
        if len({member.question for member in members}) != 1:
            raise DatasetError(f"{path}: pair {pair_id!r} changes the question")


__all__ = ["DEFAULT_DATASET", "DatasetError", "load_dataset"]
