"""The golden dataset: its schema, its loader, and the integrity checks it must pass.

A dataset is only worth what its expectations are worth. Two failure modes decide
that, and both are structural rather than a matter of care:

* **An expectation copied from the system's output measures nothing.** Every field
  here is a *constraint derived from the documented rules* — the planner's split,
  the critic's score, the outcome table in ``docs/architecture.md`` — not a
  recording of what the loop happened to produce. The schema forbids unknown
  fields and carries no place to store a report, an answer, or a snippet, so a
  transcript cannot be pasted into a case even by accident.
* **An expectation nothing can satisfy is worse than no expectation.** A case
  demanding a citation from a run it also declares must retrieve nothing, or a
  repeated passage from a one-step budget, would fail forever and teach nobody
  anything. :func:`validate_dataset` rejects those before a runner spends a step.

Provenance is checked against the committed corpus rather than trusted: a case may
only name a ``chunk_id`` or a ``source_path`` that exists. A typo in a fixture id
is otherwise indistinguishable from a retrieval regression.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentic_rag.tools import DEFAULT_CORPUS, Document

DATASET_SCHEMA_VERSION: Final = "1.0.0"
"""Schema every case in a dataset must declare. A loader refuses anything else."""

SPEC_SHORT_QUESTION_CHARS: Final = 80
"""Length under which the documented planner rule yields exactly one sub-question.

Restated here from ``docs/architecture.md`` rather than imported from the planner:
the dataset encodes what the system is *specified* to do, and a constant imported
from the system under test cannot disagree with it. ``tests/evals`` asserts the two
still match, so drift is a test failure instead of a silent re-baselining.
"""

SPEC_MAX_SUB_QUESTIONS: Final = 3
"""Cap the documented planner rule places on a plan."""

CaseCategory = Literal[
    "single_source_answerable",
    "multi_concept",
    "no_evidence_refusal",
    "budget_pressure_partial",
    "duplicate_evidence",
    "text_normalization",
]
"""The behaviour slices the dataset covers, one per axis the loop can fail on."""

CASE_CATEGORIES: Final[tuple[CaseCategory, ...]] = (
    "single_source_answerable",
    "multi_concept",
    "no_evidence_refusal",
    "budget_pressure_partial",
    "duplicate_evidence",
    "text_normalization",
)
"""Every category, in the order a scorecard lists them."""

ExpectedStatus = Literal["done", "refused", "budget_exhausted"]
"""Terminal statuses a case may expect.

``degraded`` is deliberately absent. The status is declared in the agent's status
enum but no free-path tool can produce it, so a case expecting it would be an
expectation nothing can satisfy — which is the thing this module exists to reject.
"""

ExpectedStopReason = Literal[
    "evidence_sufficient",
    "no_evidence",
    "insufficient_evidence",
    "budget_spent",
]
"""Stop reasons a case may expect, from the loop's closed set."""

_REASONS_FOR_STATUS: Final[dict[ExpectedStatus, frozenset[str]]] = {
    "done": frozenset({"evidence_sufficient"}),
    "refused": frozenset({"no_evidence", "insufficient_evidence"}),
    "budget_exhausted": frozenset({"budget_spent"}),
}
"""The outcome table in ``docs/architecture.md``, as a lookup a validator can apply."""

_CASE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
"""Case ids are kebab-case so they are stable in a filename, a diff and a URL."""

_WHITESPACE = re.compile(r"\s+")


class DatasetError(BaseModel):
    """One reason a dataset cannot be evaluated.

    Errors are collected rather than raised one at a time: a curator fixing a
    dataset wants every problem in the file, not the first one.
    """

    model_config = ConfigDict(frozen=True)

    case_id: str | None = Field(
        default=None,
        description="Case the problem belongs to, or None when it spans the file.",
    )
    code: str = Field(description="Stable slug for the kind of problem.")
    detail: str = Field(description="What is wrong, in a sentence a curator can act on.")


class EvalCase(BaseModel):
    """One evaluation case: a question, the controls it runs under, and its constraints.

    Every ``expected_*`` field is a constraint the documented rules imply, and each
    case states the derivation in :attr:`rationale` so a reader can check the
    expectation without running anything.

    Unknown fields are rejected. That is what keeps a report, an answer or a
    model transcript out of the dataset: there is nowhere to put one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(description="Schema this record was written against.")
    id: str = Field(min_length=1, description="Stable kebab-case identifier.")
    category: CaseCategory = Field(description="Behaviour slice this case belongs to.")
    question: str = Field(
        min_length=1,
        max_length=8_000,
        description="The research question, passed to the loop unmodified.",
    )
    max_steps: int = Field(ge=1, le=20, description="Step budget the run is given.")
    top_k: int = Field(ge=1, le=50, description="Passages one retrieval step may return.")
    expected_terminal_status: ExpectedStatus = Field(
        description="Terminal status the documented outcome table implies."
    )
    expected_stop_reason: ExpectedStopReason = Field(
        description="Stop reason the documented outcome table implies."
    )
    expected_min_citations: int = Field(
        default=0,
        ge=0,
        description="Fewest citations the report must carry.",
    )
    expected_max_citations: int | None = Field(
        default=None,
        ge=0,
        description="Most citations the report may carry. None leaves it unbounded.",
    )
    expected_source_paths: tuple[str, ...] = Field(
        default=(),
        description="Source paths that must appear among the citations. A subset, not the set.",
    )
    expected_chunk_ids: tuple[str, ...] = Field(
        default=(),
        description="Chunk ids that must appear in the gathered evidence. A subset, not the set.",
    )
    expected_min_plan_size: int = Field(
        default=1,
        ge=1,
        le=SPEC_MAX_SUB_QUESTIONS,
        description="Fewest sub-questions the planner rule implies for this question.",
    )
    expects_repeated_evidence: bool = Field(
        default=False,
        description="Two steps must return one chunk id, which the state must store once.",
    )
    normalization_group: str | None = Field(
        default=None,
        description="Cases in one group differ only in surface form and must behave alike.",
    )
    rationale: str = Field(
        min_length=20,
        description="Why the documented rules imply this expectation.",
    )

    @property
    def normalized_question(self) -> str:
        """Return the question with case and whitespace flattened, for duplicate checks."""
        return _WHITESPACE.sub(" ", self.question).strip().casefold()


class EvalDataset(BaseModel):
    """A loaded dataset and the identity of the file it came from.

    The digest is over the raw bytes, so a scorecard names the exact file it
    scored and a reviewer can tell a re-run from a re-curation.
    """

    model_config = ConfigDict(frozen=True)

    path: str = Field(description="Path the dataset was loaded from, as given.")
    sha256: str = Field(description="Digest of the file's bytes.")
    cases: tuple[EvalCase, ...] = Field(description="Cases in file order.")

    @property
    def case_count(self) -> int:
        """Return how many cases the dataset holds."""
        return len(self.cases)

    def counts_by_category(self) -> dict[str, int]:
        """Return how many cases each category holds, categories in declared order."""
        counts: dict[str, int] = {category: 0 for category in CASE_CATEGORIES}
        for case in self.cases:
            counts[case.category] += 1
        return counts

    def __iter__(self) -> Iterator[EvalCase]:  # type: ignore[override]
        """Iterate the cases in file order."""
        return iter(self.cases)


class DatasetInvalid(RuntimeError):
    """A dataset failed integrity validation and cannot be evaluated.

    Raised rather than reported as a low score: a broken input produces a
    meaningless scorecard, and a meaningless scorecard that exits zero is worse
    than no scorecard at all.
    """

    def __init__(self, errors: Sequence[DatasetError]) -> None:
        """Carry every problem found, not just the first."""
        self.errors = tuple(errors)
        listed = "; ".join(f"{error.case_id or '<file>'}: {error.code}" for error in self.errors)
        super().__init__(f"{len(self.errors)} dataset problem(s): {listed}")


def read_cases(path: Path | str) -> tuple[tuple[EvalCase, ...], tuple[DatasetError, ...]]:
    """Parse a JSONL dataset into cases, collecting per-line problems.

    Args:
        path: File to read. One JSON object per line; blank lines are skipped.

    Returns:
        The cases that parsed, in file order, and the problems that stopped the
        rest from parsing.

    Raises:
        FileNotFoundError: The dataset file does not exist.
    """
    cases: list[EvalCase] = []
    errors: list[DatasetError] = []
    text = Path(path).read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError as error:
            errors.append(
                DatasetError(code="unparsable_line", detail=f"line {number} is not JSON: {error}")
            )
            continue
        if not isinstance(payload, dict):
            errors.append(
                DatasetError(code="not_an_object", detail=f"line {number} is not a JSON object")
            )
            continue
        try:
            cases.append(EvalCase.model_validate(payload))
        except ValidationError as error:
            identifier = payload.get("id")
            errors.append(
                DatasetError(
                    case_id=identifier if isinstance(identifier, str) else None,
                    code="schema_violation",
                    detail=f"line {number} does not match the case schema: {error}",
                )
            )
    return tuple(cases), tuple(errors)


def _check_identity(cases: Sequence[EvalCase]) -> list[DatasetError]:
    """Return problems with ids and with questions repeating each other."""
    errors: list[DatasetError] = []
    seen_ids: set[str] = set()
    seen_questions: dict[str, str] = {}
    seen_normalized: dict[str, EvalCase] = {}

    for case in cases:
        if case.schema_version != DATASET_SCHEMA_VERSION:
            errors.append(
                DatasetError(
                    case_id=case.id,
                    code="unsupported_schema_version",
                    detail=(
                        f"declares schema {case.schema_version!r}; "
                        f"this loader reads {DATASET_SCHEMA_VERSION!r}"
                    ),
                )
            )
        if not _CASE_ID.match(case.id):
            errors.append(
                DatasetError(case_id=case.id, code="malformed_id", detail="id is not kebab-case")
            )
        if case.id in seen_ids:
            errors.append(
                DatasetError(case_id=case.id, code="duplicate_id", detail="id appears twice")
            )
        seen_ids.add(case.id)

        if case.question in seen_questions:
            errors.append(
                DatasetError(
                    case_id=case.id,
                    code="duplicate_question",
                    detail=f"question repeats case {seen_questions[case.question]!r} verbatim",
                )
            )
        seen_questions.setdefault(case.question, case.id)

        twin = seen_normalized.get(case.normalized_question)
        if twin is not None and (
            case.normalization_group is None
            or twin.normalization_group != case.normalization_group
        ):
            # Two questions equal once case and whitespace are flattened are the
            # same case padding the count — unless they are a normalization pair,
            # where being surface variants of one question is the whole point.
            errors.append(
                DatasetError(
                    case_id=case.id,
                    code="duplicate_normalized_question",
                    detail=(
                        f"question matches case {twin.id!r} after normalization, and the two "
                        "do not share a normalization_group"
                    ),
                )
            )
        seen_normalized.setdefault(case.normalized_question, case)
    return errors


def _check_outcome(case: EvalCase) -> list[DatasetError]:
    """Return problems with the terminal status, the reason, and the citation bounds."""
    errors: list[DatasetError] = []
    allowed = _REASONS_FOR_STATUS[case.expected_terminal_status]
    if case.expected_stop_reason not in allowed:
        errors.append(
            DatasetError(
                case_id=case.id,
                code="impossible_outcome",
                detail=(
                    f"status {case.expected_terminal_status!r} never carries reason "
                    f"{case.expected_stop_reason!r}; allowed: {sorted(allowed)}"
                ),
            )
        )

    ceiling = case.max_steps * case.top_k
    if (
        case.expected_max_citations is not None
        and case.expected_min_citations > case.expected_max_citations
    ):
        errors.append(
            DatasetError(
                case_id=case.id,
                code="inverted_citation_bounds",
                detail=(
                    f"expected_min_citations {case.expected_min_citations} exceeds "
                    f"expected_max_citations {case.expected_max_citations}"
                ),
            )
        )
    if case.expected_min_citations > ceiling:
        errors.append(
            DatasetError(
                case_id=case.id,
                code="unreachable_citation_floor",
                detail=(
                    f"expected_min_citations {case.expected_min_citations} exceeds the "
                    f"{ceiling} passage(s) a budget of {case.max_steps} step(s) at top_k "
                    f"{case.top_k} can return"
                ),
            )
        )

    if case.expected_stop_reason == "no_evidence":
        if case.expected_min_citations or case.expected_max_citations not in (0, None):
            errors.append(
                DatasetError(
                    case_id=case.id,
                    code="citations_expected_from_no_evidence",
                    detail="a run that retrieved nothing cites nothing",
                )
            )
        if case.expected_chunk_ids or case.expected_source_paths:
            errors.append(
                DatasetError(
                    case_id=case.id,
                    code="provenance_expected_from_no_evidence",
                    detail="a run that retrieved nothing has no provenance to expect",
                )
            )

    if case.expects_repeated_evidence and case.max_steps < 2:
        errors.append(
            DatasetError(
                case_id=case.id,
                code="repeat_needs_two_steps",
                detail="one chunk cannot be returned by two steps under a one-step budget",
            )
        )
    return errors


def _check_plan_bounds(case: EvalCase) -> list[DatasetError]:
    """Return problems with the expected plan size under the documented planner rule."""
    errors: list[DatasetError] = []
    is_short = len(case.question.strip()) < SPEC_SHORT_QUESTION_CHARS
    if is_short and case.expected_min_plan_size != 1:
        errors.append(
            DatasetError(
                case_id=case.id,
                code="plan_size_contradicts_length",
                detail=(
                    f"a question under {SPEC_SHORT_QUESTION_CHARS} characters is one "
                    f"sub-question, so expected_min_plan_size must be 1, not "
                    f"{case.expected_min_plan_size}"
                ),
            )
        )
    if case.expected_min_plan_size > case.max_steps:
        errors.append(
            DatasetError(
                case_id=case.id,
                code="plan_exceeds_budget",
                detail=(
                    f"a plan of {case.expected_min_plan_size} sub-question(s) cannot be walked "
                    f"under a budget of {case.max_steps} step(s)"
                ),
            )
        )
    return errors


def _check_provenance(case: EvalCase, corpus: Sequence[Document]) -> list[DatasetError]:
    """Return problems with provenance that the committed corpus cannot back."""
    errors: list[DatasetError] = []
    by_id = {document.chunk_id: document for document in corpus}
    known_paths = {document.source_path for document in corpus}

    for chunk_id in case.expected_chunk_ids:
        if chunk_id not in by_id:
            errors.append(
                DatasetError(
                    case_id=case.id,
                    code="unknown_chunk_id",
                    detail=f"chunk id {chunk_id!r} is not in the corpus this dataset targets",
                )
            )
    for source_path in case.expected_source_paths:
        if source_path not in known_paths:
            errors.append(
                DatasetError(
                    case_id=case.id,
                    code="unknown_source_path",
                    detail=f"source path {source_path!r} is not in the corpus",
                )
            )
    for chunk_id in case.expected_chunk_ids:
        document = by_id.get(chunk_id)
        if (
            document is not None
            and case.expected_source_paths
            and document.source_path not in case.expected_source_paths
        ):
            errors.append(
                DatasetError(
                    case_id=case.id,
                    code="provenance_disagrees",
                    detail=(
                        f"chunk {chunk_id!r} lives in {document.source_path!r}, which the case "
                        "does not list among its expected source paths"
                    ),
                )
            )

    corpus_size = len(corpus)
    if case.expected_min_citations > corpus_size:
        errors.append(
            DatasetError(
                case_id=case.id,
                code="citation_floor_exceeds_corpus",
                detail=(
                    f"expected_min_citations {case.expected_min_citations} exceeds the "
                    f"{corpus_size} distinct passage(s) the corpus holds"
                ),
            )
        )
    return errors


def _check_category(case: EvalCase) -> list[DatasetError]:
    """Return problems where a case does not exercise what its slice claims to.

    A slice whose members do not test the axis they are filed under makes a
    per-slice score meaningless while still looking like coverage.
    """
    errors: list[DatasetError] = []

    def wrong(code: str, detail: str) -> None:
        errors.append(DatasetError(case_id=case.id, code=code, detail=detail))

    if case.category == "single_source_answerable":
        if case.expected_terminal_status != "done":
            wrong("slice_mismatch", "an answerable case must expect status 'done'")
        if len(case.expected_source_paths) != 1:
            wrong("slice_mismatch", "a single-source case must name exactly one source path")
    elif case.category == "multi_concept":
        if case.expected_min_plan_size < 2:
            wrong("slice_mismatch", "a multi-concept case must expect a plan of at least 2")
    elif case.category == "no_evidence_refusal":
        if case.expected_terminal_status != "refused":
            wrong("slice_mismatch", "a refusal case must expect status 'refused'")
    elif case.category == "budget_pressure_partial":
        if case.expected_stop_reason != "budget_spent":
            wrong("slice_mismatch", "a budget-pressure case must expect reason 'budget_spent'")
    elif case.category == "duplicate_evidence":
        if not case.expects_repeated_evidence:
            wrong("slice_mismatch", "a duplicate-evidence case must expect repeated evidence")
    elif case.category == "text_normalization" and case.normalization_group is None:
        wrong("slice_mismatch", "a normalization case must declare a normalization_group")
    return errors


def _check_normalization_groups(cases: Sequence[EvalCase]) -> list[DatasetError]:
    """Return problems with groups that cannot demonstrate surface invariance."""
    errors: list[DatasetError] = []
    groups: dict[str, list[EvalCase]] = {}
    for case in cases:
        if case.normalization_group is not None:
            groups.setdefault(case.normalization_group, []).append(case)

    for name, members in sorted(groups.items()):
        if len(members) < 2:
            errors.append(
                DatasetError(
                    case_id=members[0].id,
                    code="lonely_normalization_group",
                    detail=(
                        f"group {name!r} has one member; invariance needs a pair to compare"
                    ),
                )
            )
            continue
        head = members[0]
        for member in members[1:]:
            same = (
                member.expected_terminal_status == head.expected_terminal_status
                and member.expected_stop_reason == head.expected_stop_reason
                and set(member.expected_chunk_ids) == set(head.expected_chunk_ids)
                and member.max_steps == head.max_steps
                and member.top_k == head.top_k
            )
            if not same:
                errors.append(
                    DatasetError(
                        case_id=member.id,
                        code="group_expects_divergence",
                        detail=(
                            f"group {name!r} exists to assert that surface form changes nothing, "
                            f"so every member must expect what {head.id!r} expects"
                        ),
                    )
                )
    return errors


def validate_dataset(
    cases: Sequence[EvalCase],
    *,
    corpus: Sequence[Document] = DEFAULT_CORPUS,
    minimum_cases: int = 48,
    required_categories: Iterable[CaseCategory] = CASE_CATEGORIES,
) -> tuple[DatasetError, ...]:
    """Return every reason ``cases`` could not be evaluated honestly.

    Args:
        cases: Parsed cases, in file order.
        corpus: The fixture the dataset targets. Provenance is checked against it.
        minimum_cases: Floor on dataset size. A dataset that shrinks below the size
            it was published at is a weakened dataset, so the floor is checked
            rather than assumed.
        required_categories: Slices that must each hold at least one case.

    Returns:
        The problems found, empty when the dataset is sound.
    """
    errors: list[DatasetError] = list(_check_identity(cases))
    for case in cases:
        errors.extend(_check_outcome(case))
        errors.extend(_check_plan_bounds(case))
        errors.extend(_check_provenance(case, corpus))
        errors.extend(_check_category(case))
    errors.extend(_check_normalization_groups(cases))

    if len(cases) < minimum_cases:
        errors.append(
            DatasetError(
                code="dataset_too_small",
                detail=f"{len(cases)} case(s) is below the floor of {minimum_cases}",
            )
        )
    present = {case.category for case in cases}
    for category in required_categories:
        if category not in present:
            errors.append(
                DatasetError(
                    code="missing_category",
                    detail=f"no case covers the {category!r} slice",
                )
            )
    return tuple(errors)


def load_dataset(
    path: Path | str,
    *,
    corpus: Sequence[Document] = DEFAULT_CORPUS,
    minimum_cases: int = 48,
) -> EvalDataset:
    """Read and validate a dataset, or refuse to hand back a broken one.

    Args:
        path: JSONL file to load.
        corpus: The fixture provenance is checked against.
        minimum_cases: Floor on dataset size.

    Returns:
        The validated dataset, carrying the digest of the bytes it was read from.

    Raises:
        DatasetInvalid: Parsing or validation found problems.
        FileNotFoundError: The dataset file does not exist.
    """
    source = Path(path)
    cases, parse_errors = read_cases(source)
    errors = list(parse_errors) + list(
        validate_dataset(cases, corpus=corpus, minimum_cases=minimum_cases)
    )
    if errors:
        raise DatasetInvalid(errors)
    return EvalDataset(
        path=source.as_posix(),
        sha256=file_digest(source),
        cases=tuple(cases),
    )


def file_digest(path: Path | str) -> str:
    """Return the SHA-256 of a file's bytes, as lowercase hex.

    Args:
        path: File to digest.

    Returns:
        The hex digest, prefixed with the algorithm so an artifact says what it is.
    """
    return f"sha256:{hashlib.sha256(Path(path).read_bytes()).hexdigest()}"


def dump_case(case: EvalCase) -> str:
    """Return one dataset line for ``case``, with stable key order.

    Args:
        case: The case to serialise.

    Returns:
        A single-line JSON object, keys in the schema's declaration order so a
        regenerated dataset diffs cleanly against the committed one.
    """
    payload: dict[str, Any] = case.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, separators=(", ", ": "))
