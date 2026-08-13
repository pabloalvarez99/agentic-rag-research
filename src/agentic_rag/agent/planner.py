"""Turning a question into the sub-questions one retrieval call each can answer.

The planner is deterministic and reads nothing but its argument. That is the
point of it at this milestone: a plan produced by a model is a plan that differs
between two runs of the same question, and until the loop's control flow, budget
accounting and stop rule are provably correct, a varying plan makes every failure
ambiguous — was the loop wrong, or was the plan different?

The rule is mechanical, and stated in ``docs/architecture.md``:

* A short question is already a single retrieval. Splitting it invents structure
  that was never in the text.
* A long question is usually several questions punctuated together. It is split
  on the joins people actually write — ``and``, ``then``, and question marks —
  and capped, because a plan longer than the step budget guarantees a run that
  ends mid-plan.

The planner does not retrieve, and it does not answer from parametric memory.
"""

from __future__ import annotations

import re
from typing import Final

from agentic_rag.text import keyword_terms

SHORT_QUESTION_CHARS: Final = 80
"""Length under which a question is treated as one retrieval, not several."""

MAX_SUB_QUESTIONS: Final = 3
"""Cap on a plan. Above this a plan cannot finish inside a normal step budget."""

_SPLIT = re.compile(r"\band\b|\bthen\b|\?", flags=re.IGNORECASE)
"""The joins a compound question is written with."""

_TRIM = " \t\n,;:.-—"
"""Punctuation left dangling on a fragment once its join word is removed."""


def _clean(fragment: str) -> str:
    """Return ``fragment`` without the whitespace and punctuation a split leaves."""
    return fragment.strip().strip(_TRIM).strip()


def plan_question(question: str) -> list[str]:
    """Return the ordered sub-questions to retrieve for, one call each.

    A fragment is kept only when it carries at least one scoring term: a split
    can leave ``"and"``-joined filler that would spend a step retrieving for
    nothing. Repeats are dropped case-insensitively for the same reason — the
    second retrieval of an identical sub-question returns identical passages,
    and the state would deduplicate every one of them after paying for the step.

    Args:
        question: The research question as it was asked.

    Returns:
        Between one and :data:`MAX_SUB_QUESTIONS` sub-questions, in the order
        they appear in the question. Never empty: when nothing useful survives
        the split, the whole question is the plan, which is the honest fallback
        rather than a run with nothing to do.
    """
    whole = _clean(question)
    if len(question.strip()) < SHORT_QUESTION_CHARS:
        return [whole or question.strip()]

    kept: list[str] = []
    seen: set[str] = set()
    for fragment in _SPLIT.split(question):
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

    return kept or [whole or question.strip()]
