"""Finished runs, kept long enough to be fetched, downloaded and compared.

A run used to exist only inside the response that carried it. Close the tab and the
evidence was gone; the only way to see that trace again was to run the question again
and trust that the second run was the first one. This module gives a run an identity
that outlives its response: it is stored under its correlation id, and
``GET /v1/runs/{id}`` serves it back.

Three properties are load-bearing, and each of them is a decision:

* **Keyed, never "the last one".** ``POST /v1/research/trace`` deliberately performs the
  run rather than reading a stored slot, because a single "most recent trace" is shared
  mutable state that two concurrent callers race for — the second one downloads the
  first one's evidence. A store keyed by correlation id has no such slot: a caller can
  only fetch the id it was given.
* **Bounded and in-process.** It holds at most :data:`DEFAULT_RUN_CAPACITY` runs and
  evicts the oldest. It is memory, not a database: nothing is written to disk, nothing
  survives a restart, and on a serverless host a second instance knows nothing about the
  first one's runs. That is stated in the API description and in the 404, because a
  reader who assumes durability here would assume it about the wrong thing.
* **Whole runs only.** Only a run that reached a terminal status is stored. A partial
  artifact would be indistinguishable from a complete one the moment it was fetched.

The stored artifact carries the stop reason as a field of its own. The wire contract of
``POST /v1/research`` deliberately leaves it in the terminal ``stop`` event; an artifact
is read by someone comparing runs, and making them parse a trace to learn why a run
stopped is making them re-implement the loop's own accounting.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field

from agentic_rag.agent.state import ResearchState, ResearchStatus, StopReason, TraceEvent
from agentic_rag.agent.synthesizer import Citation
from agentic_rag.notes import Note

DEFAULT_RUN_CAPACITY: Final = 32
"""Runs kept before the oldest is evicted.

Enough that a reviewer can open several runs, download one, and still fetch the first;
small enough that a process holding the maximum is holding a few hundred kilobytes.
"""

RUNS_PATH: Final = "/v1/runs"
"""Prefix every stored run is served under."""


class RunArtifact(BaseModel):
    """One finished run, as it is stored and served.

    Frozen: an artifact that can be edited after the run finished is an artifact whose
    trace and whose report can disagree.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(description="Correlation id of the run, and its id in the store.")
    question: str = Field(description="The question as it was asked.")
    retriever: str = Field(description="Backend the run's steps were spent on.")
    status: ResearchStatus = Field(description="How the run ended. Always terminal.")
    stop_reason: StopReason = Field(description="Why the loop stopped, from the closed set.")
    report: str = Field(description="The composed report, or the refusal and its gaps.")
    citations: tuple[Citation, ...] = Field(
        default=(),
        description="One entry per marker in the report, in marker order.",
    )
    notes: tuple[Note, ...] = Field(
        default=(),
        description="What the run relied on, in the order the claims were written.",
    )
    steps_used: int = Field(ge=0, description="Retrieval steps the run actually spent.")
    max_steps: int = Field(ge=1, description="The budget the run was given.")
    trace: tuple[TraceEvent, ...] = Field(
        default=(),
        description="Every event the run recorded, oldest first, ending in 'stop'.",
    )

    @classmethod
    def from_state(cls, state: ResearchState, *, request_id: str, retriever: str) -> Self:
        """Return the artifact for a finished run.

        Args:
            state: The state a runner returned.
            request_id: Correlation id the run was served under.
            retriever: Name of the backend the run's steps were spent on.

        Returns:
            The artifact, ready to store.

        Raises:
            ValueError: The run is unfinished, has no stop reason, or composed no
                report. Storing any of those would put an artifact in the store that
                cannot be told apart from a complete one once it is fetched.
        """
        if not state.is_finished or state.stop_reason is None:
            raise ValueError("only a run that reached a terminal status can be stored")
        if state.report is None:
            raise ValueError(f"the run ended {state.status.value!r} without composing a report")
        return cls(
            request_id=request_id,
            question=state.question,
            retriever=retriever,
            status=state.status,
            stop_reason=state.stop_reason,
            report=state.report,
            citations=tuple(state.citations),
            notes=tuple(state.notes),
            steps_used=state.steps_taken,
            max_steps=state.max_steps,
            trace=tuple(state.trace),
        )


class RunStore:
    """The last ``capacity`` finished runs, oldest evicted first.

    Every method takes a lock. The store is the one piece of shared mutable state the
    runtime surface has, and the route handlers are plain ``def``, so FastAPI runs them
    in a thread pool and two requests genuinely write at the same time.
    """

    def __init__(self, capacity: int = DEFAULT_RUN_CAPACITY) -> None:
        """Build an empty store.

        Args:
            capacity: How many runs to keep.

        Raises:
            ValueError: ``capacity`` is not at least one. A store that keeps nothing
                would make every fetch a 404 while still looking configured.
        """
        if capacity < 1:
            raise ValueError("a run store keeps at least one run")
        self._capacity = capacity
        self._runs: OrderedDict[str, RunArtifact] = OrderedDict()
        self._lock = Lock()

    @property
    def capacity(self) -> int:
        """Return how many runs this store keeps."""
        return self._capacity

    def __len__(self) -> int:
        """Return how many runs are currently stored."""
        with self._lock:
            return len(self._runs)

    def put(self, artifact: RunArtifact) -> None:
        """Store one finished run, evicting the oldest if the store is full.

        Re-storing an id replaces it and moves it to newest. A caller that supplies its
        own ``X-Request-ID`` can collide with itself; keeping the later run is the only
        answer that does not serve one run's report with another run's trace.

        Args:
            artifact: The finished run to store.
        """
        with self._lock:
            self._runs.pop(artifact.request_id, None)
            self._runs[artifact.request_id] = artifact
            while len(self._runs) > self._capacity:
                self._runs.popitem(last=False)

    def get(self, request_id: str) -> RunArtifact | None:
        """Return the stored run, or ``None`` when this process does not have it.

        Fetching does not refresh a run's position: eviction order is the order runs
        finished, so what is dropped is always the oldest run rather than the least
        recently read. A reviewer reading one run repeatedly should not push another
        reviewer's run out of the store.

        Args:
            request_id: Correlation id of the run.

        Returns:
            The artifact, or ``None``.
        """
        with self._lock:
            return self._runs.get(request_id)

    def ids(self) -> tuple[str, ...]:
        """Return the stored ids, oldest first."""
        with self._lock:
            return tuple(self._runs)


__all__ = ["DEFAULT_RUN_CAPACITY", "RUNS_PATH", "RunArtifact", "RunStore"]
