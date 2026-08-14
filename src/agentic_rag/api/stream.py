"""``GET /v1/research/stream`` — the same run, watched while it happens.

A finished run answers "what did it do?". A stream answers "what is it doing?", and
those are different questions for the only reader who matters here: someone deciding
whether this loop is bounded. Watching ``plan_created`` arrive, then a ``tool_call``,
then the ``critique`` arithmetic that decided to spend another step, is the difference
between being told the loop is bounded and seeing it stop.

Server-sent events, not WebSockets: the traffic is one-directional and short-lived, a
browser needs no library for it, and ``curl`` reads it without a client. Three event
names, and the contract is exactly this:

* ``trace`` — one event per recorded step, in order, carrying the same object the
  ``trace`` array of ``POST /v1/research`` carries, ``offset`` included. A client that
  drops the connection knows precisely where it stopped.
* ``done`` — the run finished. Carries the terminal status, the stop reason, the steps
  spent and the id the run is now stored under. Exactly one is sent, and always last.
* ``error`` — the run could not be produced. Carries the same
  ``{"error", "error_type", "request_id"}`` envelope every other failure uses.

**The status code is 200 even for ``error``.** By the time a run fails, the response has
already started and its status is spent; that is a property of streaming, not a claim
that nothing went wrong. A client reads the outcome from the event name, and the run
that failed is still counted by the metrics middleware under the status it promised.

The run itself executes on a worker thread and publishes events through a bounded queue.
The loop never waits on a slow reader for longer than the queue's own back-pressure, and
a disconnected client cannot leave a run half-executed: it finishes, is stored, and can
be fetched from ``GET /v1/runs/{id}`` afterwards.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from queue import Queue
from threading import Thread
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from agentic_rag.agent.state import TraceEvent
from agentic_rag.api.errors import (
    ErrorResponse,
    ErrorType,
    RequestInvalid,
    RuntimeSurfaceError,
    describe_validation_errors,
)
from agentic_rag.api.handlers import correlation_id
from agentic_rag.api.metrics import get_registry
from agentic_rag.api.request_id import REQUEST_ID_HEADER
from agentic_rag.api.routes import get_service
from agentic_rag.api.runs import RUNS_PATH
from agentic_rag.api.schemas import (
    DEFAULT_MAX_STEPS,
    DEFAULT_TOP_K,
    ResearchRequest,
    RetrieverChoice,
)
from agentic_rag.api.service import ResearchService

STREAM_PATH: Final = "/v1/research/stream"
"""Where a run is watched. ``GET`` so a browser's ``EventSource`` can subscribe to it."""

EVENT_STREAM_MEDIA_TYPE: Final = "text/event-stream"

QUEUE_CAPACITY: Final = 256
"""Events buffered before the run blocks on a slow reader.

Larger than any run this loop can produce under its own budget bounds, so on the free
path the run never blocks; bounded anyway, because a queue without a ceiling is a memory
leak wearing a reader's clothes.
"""

_STREAM_HEADERS: Final = {
    "cache-control": "no-store",
    # Tells an nginx-shaped proxy not to buffer the body. Without it a stream is
    # delivered as one block at the end, which is indistinguishable from a stream that
    # was never a stream.
    "x-accel-buffering": "no",
}

LOGGER: Final = logging.getLogger(__name__)
router = APIRouter(tags=["research"])

_END = object()
"""Sentinel put on the queue when the run has stopped publishing."""


def encode_event(name: str, payload: dict[str, Any]) -> str:
    """Return one server-sent event.

    Args:
        name: The event name a client subscribes to.
        payload: JSON-serialisable body.

    Returns:
        The wire form: an ``event:`` line, a ``data:`` line, and the blank line that
        terminates the event.
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {name}\ndata: {body}\n\n"


def _publish(events: Queue[object]) -> None:
    """Signal that no further event will be published."""
    events.put(_END)


def _drain(events: Queue[object]) -> Iterator[str]:
    """Yield encoded events until the run signals it has stopped publishing."""
    while True:
        item = events.get()
        if item is _END:
            return
        if isinstance(item, TraceEvent):
            yield encode_event("trace", item.model_dump(mode="json"))
        elif isinstance(item, tuple):
            name, payload = item
            yield encode_event(str(name), dict(payload))


def stream_run(
    service: ResearchService,
    payload: ResearchRequest,
    *,
    request: Request,
    request_id: str,
) -> Iterator[str]:
    """Run ``payload`` on a worker thread and yield its events as they are recorded.

    Args:
        service: The application's research service.
        payload: The validated request.
        request: The incoming request, read for the application's metrics registry.
        request_id: Correlation id the run is served and stored under.

    Yields:
        Encoded server-sent events: every ``trace`` event in order, then exactly one
        ``done`` or one ``error``.
    """
    events: Queue[object] = Queue(maxsize=QUEUE_CAPACITY)

    def perform() -> None:
        try:
            response = service.run(payload, request_id=request_id, listener=events.put)
        except RuntimeSurfaceError as failure:
            events.put(("error", failure.as_response(request_id).model_dump(mode="json")))
        except Exception as error:  # pragma: no cover - defensive; handlers own the rest
            LOGGER.exception("streamed run failed request_id=%s", request_id, exc_info=error)
            envelope = ErrorResponse(
                error="the service failed to complete the request",
                error_type=ErrorType.INTERNAL_ERROR,
                request_id=request_id,
            )
            events.put(("error", envelope.model_dump(mode="json")))
        else:
            get_registry(request).record_run(
                status=response.status, steps_used=response.steps_used
            )
            events.put(
                (
                    "done",
                    {
                        "request_id": response.request_id,
                        "status": response.status.value,
                        "stop_reason": stop_reason_of(response.trace),
                        "steps_used": response.steps_used,
                        "citations": len(response.citations),
                        "run": f"{RUNS_PATH}/{response.request_id}",
                    },
                )
            )
        finally:
            _publish(events)

    worker = Thread(target=perform, name=f"research-stream-{request_id}", daemon=True)
    worker.start()
    yield from _drain(events)
    worker.join()


def stop_reason_of(trace: list[TraceEvent]) -> str | None:
    """Return the reason carried by the run's terminal ``stop`` event, if it has one."""
    for event in reversed(trace):
        if event.event == "stop":
            reason = event.payload.get("reason")
            return str(reason) if reason is not None else None
    return None


@router.get(
    STREAM_PATH,
    summary="Run one bounded research loop and watch it as it happens",
    response_class=StreamingResponse,
    response_description=(
        "A `text/event-stream`: one `trace` event per recorded step, in order, then "
        "exactly one `done` carrying the terminal status, the stop reason and the id "
        "the run is stored under — or one `error` carrying the standard envelope."
    ),
)
def research_stream(
    request: Request,
    service: Annotated[ResearchService, Depends(get_service)],
    question: Annotated[str, Query(description="The research question.")],
    max_steps: Annotated[int, Query(description="Hard cap on retrieval steps.")] = (
        DEFAULT_MAX_STEPS
    ),
    top_k: Annotated[int, Query(description="Passages one step may return.")] = DEFAULT_TOP_K,
    retriever: Annotated[
        RetrieverChoice, Query(description="Retrieval backend to serve the run.")
    ] = RetrieverChoice.FAKE,
) -> StreamingResponse:
    """Stream one run's events, then its outcome.

    The parameters are the fields of ``ResearchRequest`` and are validated by that model
    rather than restated here, so the stream cannot accept a request the JSON route
    would reject.

    Args:
        request: The incoming request, read for its correlation id and registry.
        service: The application's research service.
        question: The research question.
        max_steps: Hard cap on retrieval steps for this run.
        top_k: Upper bound on passages one retrieval step returns.
        retriever: Backend to serve the run.

    Returns:
        The event stream.

    Raises:
        RequestInvalid: The parameters do not describe a runnable request. This is the
            one failure reported as a status code rather than an event, because it is
            decided before any byte of the stream is written.
    """
    request_id = correlation_id(request)
    try:
        payload = ResearchRequest.model_validate(
            {
                "question": question,
                "max_steps": max_steps,
                "top_k": top_k,
                "retriever": retriever,
            }
        )
    except ValidationError as error:
        raise RequestInvalid(describe_validation_errors(error.errors())) from error

    return StreamingResponse(
        stream_run(service, payload, request=request, request_id=request_id),
        media_type=EVENT_STREAM_MEDIA_TYPE,
        headers={REQUEST_ID_HEADER: request_id, **_STREAM_HEADERS},
    )
