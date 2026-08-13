"""Deterministic case generation, from a seed and nothing else.

Hand-written cases test the situations somebody thought of. These test the ones
nobody did — questions assembled from a vocabulary, corpora that overlap them by
accident, budgets and caps drawn from the whole allowed range, and text that a
document really can contain: other alphabets, emoji, control bytes, a marker
shape, a passage far longer than anything printable.

Every case is a pure function of its seed, so a failure is reproducible from the
integer in the test id. Nothing here is random at run time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Final

from agentic_rag.agent import ResearchState, run_research
from agentic_rag.tools import Document, FakeRetrievalBackend, RetrieveTool

_TOPICS: Final = (
    "hybrid retrieval",
    "reranking",
    "chunking",
    "citations",
    "refusal",
    "evaluation",
    "budgets",
    "traces",
)

_FILLER: Final = (
    "in practice",
    "for a production system",
    "when the corpus is small",
    "under a step budget",
    "",
)

_NASTY: Final = (
    "",
    "\x1b[31m",
    "\x00",
    "[3]",
    "再ランキング",
    "🧭",
    "ñ",
    "​",
)
"""Fragments a real document can carry and nobody sanitised on the way in."""


@dataclass(frozen=True)
class Case:
    """One generated run: what to ask, what to answer with, and under what caps."""

    seed: int
    question: str
    documents: tuple[Document, ...]
    max_steps: int
    top_k: int


def seeded_case(seed: int) -> Case:
    """Return the case for ``seed``. The same seed always returns the same case."""
    rng = random.Random(seed)
    topics = rng.sample(_TOPICS, rng.randint(1, 3))
    question = " and ".join(
        f"how does {topic} work {rng.choice(_FILLER)}".strip() for topic in topics
    )
    if rng.random() < 0.3:
        question = f"{question}?"

    documents: list[Document] = []
    for index in range(rng.randint(0, 5)):
        topic = rng.choice(_TOPICS)
        body = f"{topic.capitalize()} {rng.choice(_NASTY)} is described here {rng.choice(_FILLER)}."
        if rng.random() < 0.15:
            body = body + " padding" * 4_000
        documents.append(
            Document(
                chunk_id=f"gen-{seed}-{index}",
                source_path=f"docs/gen-{index}.md",
                text=body,
                title=rng.choice(_TOPICS),
            )
        )

    return Case(
        seed=seed,
        question=question,
        documents=tuple(documents),
        max_steps=rng.randint(1, 20),
        top_k=rng.randint(1, 5),
    )


def run_case(case: Case) -> ResearchState:
    """Run one generated case against the fixture backend over its corpus."""
    return run_research(
        case.question,
        tool=RetrieveTool(FakeRetrievalBackend(case.documents)),
        max_steps=case.max_steps,
        top_k=case.top_k,
    )


def run_seeded(seed: int) -> ResearchState:
    """Run the case for ``seed``."""
    return run_case(seeded_case(seed))
