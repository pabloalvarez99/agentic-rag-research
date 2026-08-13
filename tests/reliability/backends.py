"""Retrieval backends built to misbehave in one specific way each.

The loop's reliability is a claim about what it does when the world does not
cooperate, and the committed fixture corpus cooperates by construction. These
stand-ins fail, repeat themselves, return duplicates, or hand back text nobody
would write on purpose — one behaviour per class, so a failing test names the
condition it reproduced instead of a bundle of them.

All of them are in-process and deterministic. Nothing here opens a socket.
"""

from __future__ import annotations

from collections.abc import Sequence

from agentic_rag.tools import (
    Document,
    FakeRetrievalBackend,
    Passage,
    RetrievalBackend,
    ToolError,
)

SECRET_SHAPED = "sk-ant-live-000000000000000000"
"""A credential-shaped string planted in a failure message, never in a corpus.

The point is not that a real key would ever be there. It is that a test can
search a serialised run for one string and prove no part of a provider's error
text was copied into the state.
"""


class FailingBackend:
    """Raises :class:`ToolError` from its ``fail_from``-th call onwards.

    Args:
        fail_from: One-based index of the first call that fails. ``1`` fails
            before any evidence exists; ``2`` fails after the first step
            gathered some.
        delegate: Backend serving the calls that do not fail. Omitted, the
            committed corpus serves them.
        message: Text of the raised error, including anything a test wants to
            prove never reaches the state.
    """

    name = "failing"

    def __init__(
        self,
        *,
        fail_from: int = 1,
        delegate: RetrievalBackend | None = None,
        message: str = f"https://user:{SECRET_SHAPED}@retrieval.invalid/v1/query did not answer",
    ) -> None:
        self._fail_from = fail_from
        self._delegate = FakeRetrievalBackend() if delegate is None else delegate
        self._message = message
        self.calls = 0

    def search(self, sub_question: str, *, top_k: int) -> Sequence[Passage]:
        self.calls += 1
        if self.calls >= self._fail_from:
            raise ToolError(self._message)
        return self._delegate.search(sub_question, top_k=top_k)


class ExplodingBackend:
    """Raises something that is not a :class:`ToolError`.

    A bug inside a backend must reach the caller as the bug it is. This is the
    stand-in for one.
    """

    name = "exploding"

    def __init__(self, error: Exception | None = None) -> None:
        self._error = RuntimeError("a backend bug that is nobody's expected failure") if (
            error is None
        ) else error
        self.calls = 0

    def search(self, sub_question: str, *, top_k: int) -> Sequence[Passage]:
        self.calls += 1
        raise self._error


class StaticBackend:
    """Returns the same passages for every sub-question, whatever was asked.

    Useful for the cases where the *content* of the reply is the adversary:
    duplicate chunk ids inside one result, an empty result, ranks that lie.
    """

    name = "static"

    def __init__(self, passages: Sequence[Passage] = ()) -> None:
        self._passages = tuple(passages)
        self.calls = 0

    def search(self, sub_question: str, *, top_k: int) -> Sequence[Passage]:
        self.calls += 1
        return self._passages[:top_k]


class ThinBackend:
    """Returns one fresh passage per call, never enough to satisfy the critic.

    Every call answers, so the loop keeps its budget's worth of steps, and every
    passage is distinct, so evidence grows one per step. That is what makes it
    the right backend to measure a bound against: it produces the longest trace
    a budget allows.
    """

    name = "thin"

    def __init__(self, *, prefix: str = "thin") -> None:
        self._prefix = prefix
        self.calls = 0

    def search(self, sub_question: str, *, top_k: int) -> Sequence[Passage]:
        self.calls += 1
        return [
            Passage(
                chunk_id=f"{self._prefix}-{self.calls}",
                source_path=f"docs/{self._prefix}.md",
                text=f"Fragment {self.calls} mentions nothing the question asked about.",
                rank=1,
            )
        ]


def corpus(*texts: str) -> list[Document]:
    """Return a corpus of one document per text, ids ``doc-1``, ``doc-2``, …."""
    return [
        Document(chunk_id=f"doc-{index}", source_path=f"docs/{index}.md", text=text)
        for index, text in enumerate(texts, start=1)
    ]
