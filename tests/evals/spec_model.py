"""An independent model of the documented research loop.

This is the second opinion the golden dataset is checked against. It implements
the rules as ``docs/architecture.md`` and the module docstrings state them —
the planner's split and cap, the critic's score and threshold, the outcome table,
the fixture's lexical-overlap ranking — and it imports **nothing** from
``agentic_rag.agent``. Its only imports from the package are the shared tokeniser
and the committed corpus, which are the two things the spec is written in terms of.

Two tests use it, and they pull in opposite directions on purpose:

* ``test_spec_model.py`` runs it against the implementation over every golden
  question. Disagreement means the documentation and the code have drifted, and
  one of them is wrong.
* ``test_golden_dataset.py`` runs it against the dataset. Disagreement means an
  expectation cannot be derived from a documented rule, which is how a case that
  merely records what the implementation printed gets caught.

The honest limit: this file was written by someone who had read the
implementation, so it is independent in construction but not in origin. It
cannot catch a rule that is wrong in the same way in both places — only a rule
the code and the docs disagree about. Making that stronger needs a reader who has
seen only ``docs/architecture.md``.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

from agentic_rag.text import keyword_terms
from agentic_rag.tools.retrieve import DEFAULT_CORPUS, Document

SHORT_QUESTION_CHARS = 80
"""Below this, docs say the question is its own single sub-question."""

MAX_SUB_QUESTIONS = 3
"""Documented cap on a plan."""

SUFFICIENT_SCORE = 3
"""Documented sufficiency threshold: notes + covered question terms."""

SPLIT = re.compile(r"\band\b|\bthen\b|\?", flags=re.IGNORECASE)
"""The three joins the documented planner splits a long question on."""

TRIM = " \t\n,;:.-—"
"""Punctuation the planner trims from a fragment's edges."""


@dataclass(frozen=True)
class SpecGap:
    """A gap the documented critic names, and the follow-up it implies."""

    kind: str
    follow_up: str | None


@dataclass(frozen=True)
class SpecPrediction:
    """What the documented rules say a run of one question must look like."""

    plan: tuple[str, ...]
    steps: int
    status: str
    stop_reason: str
    score: int
    evidence_ids: tuple[str, ...]
    source_paths: tuple[str, ...] = field(default=())


def _clean(fragment: str) -> str:
    """Return a plan fragment with its edge punctuation trimmed."""
    return fragment.strip().strip(TRIM).strip()


def plan(question: str) -> tuple[str, ...]:
    """Return the sub-questions the documented planner rule produces.

    Args:
        question: The question as asked.

    Returns:
        One fragment for a short question; otherwise up to the documented cap,
        split on ``and``, ``then`` and ``?``, dropping fragments with no scoring
        term and dropping repeats.
    """
    whole = _clean(question) or question.strip()
    if len(question.strip()) < SHORT_QUESTION_CHARS:
        return (whole,)
    kept: list[str] = []
    seen: set[str] = set()
    for fragment in SPLIT.split(question):
        candidate = _clean(fragment)
        if not keyword_terms(candidate):
            continue
        folded = candidate.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        kept.append(candidate)
        if len(kept) == MAX_SUB_QUESTIONS:
            break
    return tuple(kept) or (whole,)


def document_terms(document: Document) -> set[str]:
    """Return the scoring terms of a corpus document, title and heading included."""
    return keyword_terms(
        f"{document.title or ''} {document.heading_path or ''} {document.text}"
    )


def search(
    sub_question: str,
    top_k: int,
    corpus: Sequence[Document] = DEFAULT_CORPUS,
) -> tuple[Document, ...]:
    """Return what the documented fixture ranking returns for one sub-question.

    Args:
        sub_question: The text to score against.
        top_k: Upper bound on returned passages.
        corpus: Passages to rank.

    Returns:
        Documents sharing at least one term, most overlap first, ties broken by
        corpus order, truncated to ``top_k``.
    """
    terms = keyword_terms(sub_question)
    scored = [
        (-len(terms & document_terms(document)), position, document)
        for position, document in enumerate(corpus)
    ]
    ranked = sorted(
        (entry for entry in scored if entry[0] < 0),
        key=lambda entry: (entry[0], entry[1]),
    )
    return tuple(document for _, _, document in ranked[:top_k])


def critique(
    question: str,
    evidence: Sequence[Document],
    unanswered: Sequence[str],
) -> tuple[bool, int, tuple[SpecGap, ...]]:
    """Apply the documented sufficiency rule to the evidence gathered so far.

    Args:
        question: The whole question, which is what the critic scores against.
        evidence: Distinct passages held so far.
        unanswered: Sub-questions that retrieved nothing.

    Returns:
        Whether the evidence is sufficient, the score, and the named gaps.
    """
    wanted = keyword_terms(question)
    seen: set[str] = set()
    for document in evidence:
        seen |= document_terms(document)
    covered = wanted & seen
    missing = wanted - seen
    score = len(evidence) + len(covered)
    if score >= SUFFICIENT_SCORE and evidence:
        return True, score, ()

    gaps: list[SpecGap] = []
    if not evidence and not unanswered:
        gaps.append(SpecGap("no_evidence", question))
    gaps.extend(SpecGap("unanswered_sub_question", None) for _ in unanswered)
    if missing:
        gaps.append(SpecGap("uncovered_terms", " ".join(sorted(missing))))
    if evidence and not missing:
        gaps.append(SpecGap("thin_evidence", None))
    return False, score, tuple(gaps)


def decide(*, sufficient: bool, has_evidence: bool, budget_spent: bool) -> tuple[str, str]:
    """Return the documented terminal status and stop reason.

    This is the table in ``docs/architecture.md`` under "How a run ends", in the
    order it is written there. The order is the content: a run that ran out of
    evidence and budget at once reports the shortage of evidence.

    Args:
        sufficient: Whether the critic accepted the evidence.
        has_evidence: Whether anything was retrieved at all.
        budget_spent: Whether the step budget is used up.

    Returns:
        The status and the reason it carries.
    """
    if sufficient:
        return "done", "evidence_sufficient"
    if not has_evidence:
        return "refused", "no_evidence"
    if budget_spent:
        return "budget_exhausted", "budget_spent"
    return "refused", "insufficient_evidence"


def predict(
    question: str,
    *,
    max_steps: int,
    top_k: int,
    corpus: Sequence[Document] = DEFAULT_CORPUS,
) -> SpecPrediction:
    """Return what the documented rules say a run must do with one question.

    Args:
        question: The question to run.
        max_steps: The step budget.
        top_k: Passages a single retrieval may return.
        corpus: The fixture to retrieve from.

    Returns:
        The plan, the steps spent, the terminal outcome and the evidence held.
    """
    planned = plan(question)
    pending: deque[str] = deque(planned)
    requested: set[str] = set()
    evidence: list[Document] = []
    evidence_ids: list[str] = []
    unanswered: list[str] = []
    steps = 0
    sufficient = False
    score = 0

    while pending and steps < max_steps:
        sub_question = pending.popleft()
        folded = sub_question.casefold()
        if folded in requested:
            continue
        requested.add(folded)

        hits = search(sub_question, top_k, corpus)
        steps += 1
        if not hits:
            unanswered.append(sub_question)
        for document in hits:
            if document.chunk_id not in evidence_ids:
                evidence.append(document)
                evidence_ids.append(document.chunk_id)

        sufficient, score, gaps = critique(question, evidence, unanswered)
        if sufficient:
            break

        queued = {candidate.casefold() for candidate in pending}
        for gap in gaps:
            follow_up = gap.follow_up
            if follow_up is None:
                continue
            key = follow_up.casefold()
            if key in requested or key in queued:
                continue
            pending.append(follow_up)
            queued.add(key)

    status, stop_reason = decide(
        sufficient=sufficient,
        has_evidence=bool(evidence),
        budget_spent=steps >= max_steps,
    )
    return SpecPrediction(
        plan=planned,
        steps=steps,
        status=status,
        stop_reason=stop_reason,
        score=score,
        evidence_ids=tuple(evidence_ids),
        source_paths=tuple(sorted({document.source_path for document in evidence})),
    )
