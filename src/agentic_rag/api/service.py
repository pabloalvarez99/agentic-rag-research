"""The one place a request becomes a run.

Both ways in — ``POST /v1/research`` and ``python -m agentic_rag.research`` — call
:meth:`ResearchService.run` and nothing else. That is the whole design: a second path
from a request to a run would be a second answer to "what does this agent do", and the
tests would only cover one of them.

The service adds no reasoning. It selects a backend, spends a run on it, and renders
what came back. Planning, the step budget, the stop rule and the refusal path stay in
``agentic_rag.agent``, which is where they are already tested.

Two collaborators are injected, and both exist for the same reason — **a test must not
be able to reach the network by accident**:

* ``retriever_factory`` decides which backend serves a run. The default is the only code
  here that reads the environment.
* ``runner`` performs the run. A test supplies one to produce a state the free path
  cannot reach, such as a tool failure or the declared-but-unproduced ``degraded``
  status.

The service holds no mutable state between calls, which is what makes concurrent
requests independent: there is no shared place for one request's id, question or
evidence to be seen by another.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from time import perf_counter
from typing import Final, Protocol

from agentic_rag.agent.graph import run_research
from agentic_rag.agent.state import DEFAULT_MAX_STEPS, ResearchState, TraceListener
from agentic_rag.api.errors import (
    BackendUnavailable,
    CapabilityMissing,
    RunNotReportable,
)
from agentic_rag.api.request_id import new_request_id
from agentic_rag.api.runs import RunArtifact, RunStore
from agentic_rag.api.schemas import ResearchRequest, ResearchResponse, RetrieverChoice
from agentic_rag.tools.base import ToolError
from agentic_rag.tools.retrieve import (
    DEFAULT_TOP_K,
    PRODUCTION_RAG_URL_ENV,
    FakeRetrievalBackend,
    HttpRetrievalBackend,
    RetrieveTool,
)

LOGGER: Final = logging.getLogger(__name__)
"""Runtime log. It records how a run ended, never what was asked."""


class ResearchRunner(Protocol):
    """Whatever performs a run for the service.

    Structural rather than a base class, so ``run_research`` satisfies it without
    knowing this module exists and a test satisfies it with a plain function.
    """

    def __call__(
        self,
        question: str,
        *,
        tool: RetrieveTool | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        top_k: int = DEFAULT_TOP_K,
        listener: TraceListener | None = None,
    ) -> ResearchState:
        """Research ``question`` under a step budget and return the finished state.

        ``listener``, when given, is called with each trace event as it is recorded.
        A runner is free to call it only at the end: the stream contract is that events
        arrive in order and that the last one is ``stop``, not that they arrive early.
        """


RetrieverFactory = Callable[[RetrieverChoice], RetrieveTool]
"""Turns the caller's choice of backend into the tool a run will spend its steps on."""


def build_retriever(choice: RetrieverChoice) -> RetrieveTool:
    """Return the retrieve tool for an explicitly chosen backend.

    This deliberately does **not** call ``build_retrieve_tool()``, which picks a backend
    from the environment. That function is right for a library caller who has expressed
    no preference; it is wrong here, in both directions:

    * asked for ``fake``, this must never become an HTTP call because a variable happens
      to be set in the deployment's environment;
    * asked for ``http``, this must never quietly fall back to the fixture. A caller who
      asked for a real retrieval service and silently received deterministic canned
      passages would read them as real evidence. An honest typed error is the only
      acceptable answer, and it is the one case in this milestone where refusing to
      serve is better than serving.

    Args:
        choice: The backend the caller named in the request.

    Returns:
        A retrieve tool bound to the chosen backend.

    Raises:
        CapabilityMissing: ``http`` was chosen and no retrieval service is configured.
            The message names the variable to set and never its value, which is a
            credential whenever the URL carries one.
    """
    if choice is RetrieverChoice.FAKE:
        return RetrieveTool(FakeRetrievalBackend())

    base_url = os.environ.get(PRODUCTION_RAG_URL_ENV, "").strip()
    if not base_url:
        raise CapabilityMissing(
            f"retriever {RetrieverChoice.HTTP.value!r} needs {PRODUCTION_RAG_URL_ENV} to name a "
            "running production-rag instance; this deployment has no value for it, and the "
            "free retriever is not substituted for one that was asked for explicitly"
        )
    return RetrieveTool(HttpRetrievalBackend(base_url))


def render_response(state: ResearchState, *, request_id: str) -> ResearchResponse:
    """Return the finished run as the wire contract reports it.

    Args:
        state: The state a runner returned.
        request_id: Correlation id to carry into the body.

    Returns:
        The six-field response, built from the canonical models the run produced.

    Raises:
        RunNotReportable: The run never reached a terminal status, or reached one
            without a report. Both are defects rather than provider failures.
    """
    if not state.is_finished:
        raise RunNotReportable(
            "the run did not reach a terminal status and cannot be reported"
        )
    if state.report is None:
        raise RunNotReportable(
            f"the run ended {state.status.value!r} without composing a report"
        )
    return ResearchResponse(
        status=state.status,
        report=state.report,
        citations=list(state.citations),
        steps_used=state.steps_taken,
        trace=list(state.trace),
        request_id=request_id,
    )


class ResearchService:
    """Turns a validated request into a rendered run.

    Stateless between calls by construction: everything a run needs is an argument, and
    the tool a run spends is built for that run. Two requests in flight share nothing.
    """

    def __init__(
        self,
        *,
        runner: ResearchRunner | None = None,
        retriever_factory: RetrieverFactory | None = None,
        run_store: RunStore | None = None,
    ) -> None:
        """Build the service over its collaborators.

        Args:
            runner: What performs a run. Defaults to the agent loop.
            retriever_factory: What turns a backend choice into a tool. Defaults to
                :func:`build_retriever`, the only code here that reads the environment.
            run_store: Where finished runs are kept so they can be fetched again.
                Defaults to a store of its own. It is the one piece of state this
                service holds between calls, and it is deliberate: an artifact nobody
                can fetch twice is not an artifact. It is keyed by correlation id, so
                two concurrent requests write two entries rather than racing for one.
        """
        self._run_research: ResearchRunner = run_research if runner is None else runner
        self._build_retriever: RetrieverFactory = (
            build_retriever if retriever_factory is None else retriever_factory
        )
        self._run_store = RunStore() if run_store is None else run_store

    @property
    def runs(self) -> RunStore:
        """Return the store of finished runs this service records into."""
        return self._run_store

    def run(
        self,
        request: ResearchRequest,
        *,
        request_id: str | None = None,
        listener: TraceListener | None = None,
    ) -> ResearchResponse:
        """Perform one run, store it, and render it.

        Args:
            request: The validated request.
            request_id: Correlation id established by the caller. Omitted, one is minted,
                so a run always carries an id whichever way it arrived.
            listener: Called with each trace event as the run records it. This is what
                the stream route watches a run with; every other caller passes nothing
                and sees no difference.

        Returns:
            The finished run, correlated to ``request_id``.

        Raises:
            CapabilityMissing: The chosen backend is not configured here.
            BackendUnavailable: The chosen backend failed the call.
            RunNotReportable: The runner returned something that is not a finished run.
        """
        correlation = new_request_id() if request_id is None else request_id
        tool = self._build_retriever(request.retriever)
        started = perf_counter()

        try:
            state = self._run_research(
                request.question,
                tool=tool,
                max_steps=request.max_steps,
                top_k=request.top_k,
                listener=listener,
            )
        except ToolError as error:
            # The tool's own message names the endpoint it called, which is configuration
            # and may carry a credential. It goes to this service's log and not into the
            # response: a caller learns that the backend failed, an operator learns how.
            LOGGER.warning(
                "retrieval backend %s failed request_id=%s",
                request.retriever.value,
                correlation,
                exc_info=error,
            )
            raise BackendUnavailable(
                f"the {request.retriever.value!r} retrieval backend did not serve the call"
            ) from error

        response = render_response(state, request_id=correlation)
        self._run_store.put(
            RunArtifact.from_state(
                state,
                request_id=correlation,
                retriever=request.retriever.value,
            )
        )
        LOGGER.info(
            "research run finished status=%s steps_used=%d retriever=%s "
            "citations=%d duration_ms=%.1f request_id=%s",
            response.status.value,
            response.steps_used,
            request.retriever.value,
            len(response.citations),
            (perf_counter() - started) * 1000,
            correlation,
        )
        return response
