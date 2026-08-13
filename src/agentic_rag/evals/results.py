"""What a run of the evaluation produces, and how it is written down.

Three properties of this file are load-bearing, and each exists because of a way
evaluation artifacts usually go wrong:

* **Every number carries its denominator.** A metric here is a numerator, a
  denominator and the value they imply — never a bare percentage. A rate with the
  denominator hidden is how "100% agreement" comes to mean "one case declared this
  expectation". When the denominator is zero the value is ``null`` and the reason
  is stated, because rounding an undefined rate to 1.0 turns missing coverage into
  a perfect score.
* **The artifact is reproducible on purpose.** Volatile fields are named in the
  document itself, and ``--reproducible`` writes them as a fixed placeholder so a
  clean clone can diff the file byte for byte. ``results_digest`` covers everything
  except those fields, so two runs can be compared without trusting the diff tool.
* **Writes are atomic.** The file is written beside its destination and moved into
  place, so an interrupted run leaves the previous scorecard intact rather than a
  half-written one that still parses.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

RESULTS_SCHEMA_VERSION: Final = "1.0.0"
"""Schema of the JSON document this module writes."""

VOLATILE_FIELDS: Final[tuple[str, ...]] = (
    "run.generated_at",
    "run.python_version",
    "run.platform",
)
"""Fields that differ between two identical runs, named in the artifact itself.

Nothing else may vary. Wall-clock duration is deliberately not recorded: a timing
in an artifact invites a latency claim, and a fixture over five in-process
passages cannot support one.
"""

NORMALIZED: Final = "normalized"
"""Placeholder written into every volatile field under ``--reproducible``."""


class MetricValue(BaseModel):
    """One measured rate, with the arithmetic that produced it.

    ``value`` is ``None`` exactly when ``denominator`` is zero. That case is
    reported rather than smoothed: no case declaring an expectation is missing
    coverage, and missing coverage is not agreement.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Stable slug for this metric.")
    description: str = Field(description="What it measures, in one sentence.")
    denominator_meaning: str = Field(description="What the denominator counts.")
    numerator: int = Field(ge=0, description="Cases or items that satisfied the property.")
    denominator: int = Field(ge=0, description="Cases or items the property applied to.")
    value: float | None = Field(
        default=None,
        description="numerator / denominator, or null when the denominator is zero.",
    )
    undefined_reason: str | None = Field(
        default=None,
        description="Why the value is null. Present exactly when it is.",
    )

    @classmethod
    def build(
        cls,
        *,
        id: str,  # noqa: A002 - the field is named `id` in the artifact
        description: str,
        denominator_meaning: str,
        numerator: int,
        denominator: int,
    ) -> MetricValue:
        """Return a metric, deciding the undefined case in one place.

        Args:
            id: Stable slug for the metric.
            description: What it measures.
            denominator_meaning: What the denominator counts.
            numerator: Items that satisfied the property.
            denominator: Items the property applied to.

        Returns:
            The metric, with ``value`` set only when the denominator allows one.
        """
        if denominator == 0:
            return cls(
                id=id,
                description=description,
                denominator_meaning=denominator_meaning,
                numerator=0,
                denominator=0,
                value=None,
                undefined_reason=(
                    "zero denominator: no case in this dataset declared this expectation"
                ),
            )
        return cls(
            id=id,
            description=description,
            denominator_meaning=denominator_meaning,
            numerator=numerator,
            denominator=denominator,
            value=round(numerator / denominator, 6),
        )


class ObservedRun(BaseModel):
    """What one run of the loop did, reduced to the facts a scorecard can check.

    The report text is stored as a digest rather than in full: the artifact is
    committed, and a committed file holding sixty generated reports is a file
    nobody reads and every diff touches. The digest still proves two runs produced
    the same report.
    """

    model_config = ConfigDict(frozen=True)

    status: str = Field(description="Terminal status the run recorded.")
    stop_reason: str | None = Field(description="Why the loop stopped.")
    steps_used: int = Field(ge=0, description="Tool calls the run spent.")
    plan_size: int = Field(ge=0, description="Sub-questions the planner produced.")
    evidence_ids: tuple[str, ...] = Field(description="Distinct chunk ids gathered, in order.")
    citation_markers: tuple[int, ...] = Field(description="Markers printed in the report.")
    citation_chunk_ids: tuple[str, ...] = Field(description="Chunk id behind each marker.")
    citation_source_paths: tuple[str, ...] = Field(description="Source path behind each marker.")
    repeated_evidence_ids: tuple[str, ...] = Field(
        description="Chunk ids more than one step returned, stored once.",
    )
    gap_kinds: tuple[str, ...] = Field(description="Kinds of gap the critic left unclosed.")
    trace_events: tuple[str, ...] = Field(description="Trace event names, in order.")
    backends: tuple[str, ...] = Field(description="Distinct backends that served a step.")
    report_sha256: str = Field(description="Digest of the report text.")
    report_line_count: int = Field(ge=0, description="Lines in the report.")


class ExpectationMatch(BaseModel):
    """Whether one run met each constraint its case declared.

    ``None`` means the case declared no such constraint, and is what keeps the
    corresponding denominator honest: an expectation nobody stated is not an
    expectation that was met.
    """

    model_config = ConfigDict(frozen=True)

    terminal_status: bool = Field(description="Observed status equals the expected one.")
    stop_reason: bool = Field(description="Observed stop reason equals the expected one.")
    min_plan_size: bool = Field(description="The plan is at least as long as expected.")
    citation_bounds: bool = Field(description="Citation count falls inside the declared bounds.")
    expected_sources: bool | None = Field(
        default=None,
        description="Declared source paths all appear among the citations.",
    )
    expected_chunks: bool | None = Field(
        default=None,
        description="Declared chunk ids all appear in the evidence.",
    )
    repeated_evidence: bool | None = Field(
        default=None,
        description="A chunk was returned by two steps, as the case declared it must be.",
    )

    @property
    def all_declared_met(self) -> bool:
        """Return whether every constraint the case declared was satisfied."""
        declared = (
            self.terminal_status,
            self.stop_reason,
            self.min_plan_size,
            self.citation_bounds,
            self.expected_sources,
            self.expected_chunks,
            self.repeated_evidence,
        )
        return all(flag for flag in declared if flag is not None)


class CaseResult(BaseModel):
    """One case, what it expected, what happened, and what broke.

    Expectations are echoed rather than referenced so the artifact stands on its
    own: a scorecard that only makes sense next to the dataset it scored is a
    scorecard that stops making sense the moment the dataset moves.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Case id from the dataset.")
    category: str = Field(description="Behaviour slice the case belongs to.")
    question: str = Field(description="The question, as the loop received it.")
    max_steps: int = Field(ge=1, description="Step budget the case set.")
    top_k: int = Field(ge=1, description="Passages one step could return.")
    expected: Mapping[str, Any] = Field(description="The constraints the case declared.")
    observed: ObservedRun = Field(description="What the run did.")
    matches: ExpectationMatch = Field(description="Which constraints the run met.")
    invariant_violations: Mapping[str, tuple[str, ...]] = Field(
        default_factory=dict,
        description="Violated invariant id to its messages. Empty on a clean run.",
    )
    baseline: Mapping[str, Any] = Field(
        default_factory=dict,
        description="The single-pass reference for the same question and top_k.",
    )

    @property
    def is_clean(self) -> bool:
        """Return whether the run violated no invariant."""
        return not self.invariant_violations


class InvariantOutcome(BaseModel):
    """One invariant, how widely it was checked, and where it failed."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Invariant slug.")
    description: str = Field(description="The property it proves.")
    cases_checked: int = Field(ge=0, description="Runs the invariant was applied to.")
    cases_violating: int = Field(ge=0, description="Runs that broke it.")
    violations: tuple[str, ...] = Field(
        default=(),
        description="Violation messages, prefixed with the case that produced them.",
    )

    @property
    def held(self) -> bool:
        """Return whether the invariant held on every run it was checked against."""
        return self.cases_violating == 0


class DeterminismOutcome(BaseModel):
    """Whether repeating the whole evaluation produced the same results."""

    model_config = ConfigDict(frozen=True)

    repeats: int = Field(ge=1, description="How many times the dataset was evaluated.")
    digests: tuple[str, ...] = Field(description="One digest of the case records per repeat.")
    stable: bool = Field(description="Every repeat produced the same digest.")

    @property
    def proven(self) -> bool:
        """Return whether the repeats were enough to say anything about stability.

        One repeat cannot demonstrate determinism. It is not a failure — it is an
        unproven claim, and the scorecard says so rather than implying stability
        from a single sample.
        """
        return self.repeats > 1 and self.stable


class RunMetadata(BaseModel):
    """Provenance of one evaluation run.

    Everything here is either fixed by the commit or listed in
    :data:`VOLATILE_FIELDS`. There is no timing field: see the module docstring.
    """

    model_config = ConfigDict(frozen=True)

    generated_at: str = Field(description="UTC timestamp, or the normalized placeholder.")
    python_version: str = Field(description="Interpreter version, or the placeholder.")
    platform: str = Field(description="Platform tag, or the placeholder.")
    package_version: str = Field(description="Version of the package under evaluation.")
    command: str = Field(description="The evaluation command, without absolute paths.")
    backend: str = Field(description="Retrieval backend bound for every case.")
    corpus_size: int = Field(ge=0, description="Passages the fixture corpus holds.")
    network_used: bool = Field(description="Whether any run left the process. Always false.")
    billed_usd: float = Field(description="Money spent. Zero, because the path is a fixture.")
    reproducible_mode: bool = Field(description="Volatile fields were written as placeholders.")


class DatasetMetadata(BaseModel):
    """Identity of the dataset a scorecard scored."""

    model_config = ConfigDict(frozen=True)

    path: str = Field(description="Path as given on the command line, in POSIX form.")
    sha256: str = Field(description="Digest of the dataset file's bytes.")
    schema_version: str = Field(description="Case schema the dataset declares.")
    case_count: int = Field(ge=0, description="Cases evaluated.")
    counts_by_category: Mapping[str, int] = Field(description="Cases per behaviour slice.")


class Scorecard(BaseModel):
    """The whole result of one evaluation run.

    This is the artifact. It is machine-readable first — the Markdown scorecard is
    rendered from this document and never computed separately, so the two cannot
    disagree.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str = Field(
        default=RESULTS_SCHEMA_VERSION,
        description="Schema of this document.",
    )
    volatile_fields: tuple[str, ...] = Field(
        default=VOLATILE_FIELDS,
        description="Dotted paths excluded from the digest and from reproducibility.",
    )
    evidence_class: str = Field(
        default="fixture-contract",
        description="What this artifact is evidence of. Never a quality result.",
    )
    disclaimer: str = Field(description="What the numbers do and do not support.")
    run: RunMetadata = Field(description="Provenance of the run.")
    dataset: DatasetMetadata = Field(description="Identity of the dataset scored.")
    invariants: tuple[InvariantOutcome, ...] = Field(description="Hard properties and violations.")
    determinism: DeterminismOutcome = Field(description="Repeat-run stability.")
    metrics: tuple[MetricValue, ...] = Field(description="Descriptive agreement and coverage.")
    metrics_by_category: Mapping[str, tuple[MetricValue, ...]] = Field(
        default_factory=dict,
        description="The same metrics, per behaviour slice.",
    )
    steps_distribution: Mapping[str, int] = Field(
        default_factory=dict,
        description="How many cases spent each number of steps.",
    )
    cases: tuple[CaseResult, ...] = Field(description="Per-case records, in dataset order.")
    results_digest: str = Field(
        default="",
        description="Digest over this document with volatile fields removed.",
    )

    @property
    def failed_invariants(self) -> tuple[InvariantOutcome, ...]:
        """Return the invariants that were violated by at least one run."""
        return tuple(outcome for outcome in self.invariants if not outcome.held)

    @property
    def mismatched_cases(self) -> tuple[CaseResult, ...]:
        """Return the cases whose run did not meet every constraint they declared."""
        return tuple(case for case in self.cases if not case.matches.all_declared_met)


def _strip_path(payload: dict[str, Any], dotted: str) -> None:
    """Remove one dotted path from a nested mapping, if it is there."""
    head, _, tail = dotted.partition(".")
    if not tail:
        payload.pop(head, None)
        return
    nested = payload.get(head)
    if isinstance(nested, dict):
        _strip_path(nested, tail)


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Return a stable serialisation of ``payload``, for digesting or diffing.

    Args:
        payload: Any JSON-compatible mapping.

    Returns:
        Compact JSON with sorted keys, so two equal documents produce equal bytes
        whatever order they were built in.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_of(payload: Mapping[str, Any], *, ignore: Sequence[str] = ()) -> str:
    """Return the SHA-256 of ``payload`` with ``ignore``d paths removed.

    Args:
        payload: The document to digest.
        ignore: Dotted paths to drop first, typically the volatile fields.

    Returns:
        The hex digest, prefixed with its algorithm.
    """
    reduced = json.loads(json.dumps(payload))
    for dotted in ignore:
        _strip_path(reduced, dotted)
    reduced.pop("results_digest", None)
    return f"sha256:{hashlib.sha256(canonical_json(reduced).encode('utf-8')).hexdigest()}"


def scorecard_payload(scorecard: Scorecard) -> dict[str, Any]:
    """Return the JSON document for ``scorecard``, with its digest filled in.

    Args:
        scorecard: The result to serialise.

    Returns:
        A plain mapping ready to be written or rendered, whose ``results_digest``
        covers every non-volatile field.
    """
    payload: dict[str, Any] = scorecard.model_dump(mode="json")
    payload["results_digest"] = digest_of(payload, ignore=scorecard.volatile_fields)
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> str:
    """Write ``payload`` to ``path`` atomically and return what was written.

    The file lands with a trailing newline and two-space indentation: it is
    committed, and a committed artifact is read in a diff before it is read by a
    parser.

    Args:
        path: Destination file. Parent directories are created.
        payload: The document to write.

    Returns:
        The exact text written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return text


def write_text(path: Path, text: str) -> str:
    """Write ``text`` to ``path`` atomically and return it.

    Args:
        path: Destination file. Parent directories are created.
        text: Content to write, newline-terminated by the caller.

    Returns:
        The text written, unchanged.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return text
