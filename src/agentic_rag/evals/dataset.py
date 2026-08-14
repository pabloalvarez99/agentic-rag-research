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
    {
        "answerable_multi_hop",
        "unanswerable",
        "budget_stress",
        "thin_evidence",
        "tool_budget",
    }
)
MIN_DATASET_SIZE: Final = 40
"""Season v1 control set floor (docs/SEASON.md)."""

ANSWERABLE_CATEGORIES: Final = frozenset(
    {"answerable_single_hop", "answerable_multi_hop"}
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
    if len(cases) < MIN_DATASET_SIZE:
        raise DatasetError(
            f"{path}: need at least {MIN_DATASET_SIZE} goldens for season v1, found {len(cases)}"
        )

    categories = {case.category for case in cases}
    missing = REQUIRED_CATEGORIES - categories
    if missing:
        raise DatasetError(f"{path}: missing required categories: {sorted(missing)}")

    critic = [case for case in cases if case.id == "critic-notes-exist-not-success"]
    if not critic:
        raise DatasetError(f"{path}: missing permanent critic-can-lose case id")
    if critic[0].expect.status != "refused":
        raise DatasetError(
            f"{path}: critic-notes-exist-not-success must expect refused (never weaken)"
        )

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

    _validate_difficulty_predicates(cases, path)


def _validate_difficulty_predicates(cases: list[GoldenCase], path: Path) -> None:
    """Mechanical slice difficulty checks (SEASON.md §5.3).

    Fail closed when a slice is trivially all-easy under the documented predicates.
    """
    unanswerable = [case for case in cases if case.category == "unanswerable"]
    if unanswerable and any(case.expect.status == "done" for case in unanswerable):
        raise DatasetError(f"{path}: unanswerable slice must never expect done")

    thin = [case for case in cases if case.category in {"thin_evidence", "off_topic_notes"}]
    if thin and any(case.expect.status == "done" for case in thin):
        raise DatasetError(f"{path}: thin/off-topic slice must never expect done")

    budget = [case for case in cases if case.category == "budget_stress"]
    if budget:
        statuses = {case.expect.status for case in budget}
        low = [case for case in budget if case.max_steps <= 1]
        if len(low) * 2 < len(budget) and len(statuses) < 2:
            raise DatasetError(
                f"{path}: budget_stress slice needs varied status or ≥50% max_steps≤1"
            )

    answerable = [case for case in cases if case.category in ANSWERABLE_CATEGORIES]
    if answerable:
        multi = [case for case in answerable if case.category == "answerable_multi_hop"]
        multi_ratio = len(multi) / len(answerable)
        if multi_ratio < 0.2 and all(case.expect.steps_used == 1 for case in answerable):
            raise DatasetError(
                f"{path}: answerable slice is all single-step trivial (need multi-hop share)"
            )

    tool = [case for case in cases if case.category == "tool_budget"]
    if tool and not any(case.expect.stop_reason == "tool_budget_spent" for case in tool):
        raise DatasetError(f"{path}: tool_budget slice needs at least one tool_budget_spent")


__all__ = ["DEFAULT_DATASET", "DatasetError", "MIN_DATASET_SIZE", "load_dataset"]
