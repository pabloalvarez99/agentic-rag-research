"""What an operator can scrape, and the one place a run is counted.

This module adds no reasoning to the loop. It counts four things an operator needs
before this service is worth putting behind a probe — that the process is up, how many
requests it served, how many runs finished in each terminal status, and how many
retrieval steps those runs spent — and renders them in the Prometheus text exposition
format.

Three decisions are worth stating, because each is a failure mode the rest of this
package already reasons about:

* **No client library.** The exposition format is a handful of lines of text, and a
  dependency that exists to emit them would be a dependency in the credential-free
  install path for no capability the operator does not already get here.
* **The path label is a known route or ``other``.** A counter labelled with whatever
  string a caller happened to request is a cardinality leak with a 404 scanner on the
  other end of it. The set of labels this service can ever emit is fixed at build time.
* **The registry lives on the application, not in a module global.** ``create_app`` is a
  factory precisely so two applications in one test session do not share state; a
  module-level counter would quietly undo that, and the first test to assert on a total
  would depend on which test ran before it.

Counters are process-local and reset when the process does, which is what a Prometheus
counter is. Nothing here is persisted, and nothing here records what was asked — the
question is never a label.
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Sequence
from typing import Final

from fastapi import Request
from starlette.routing import BaseRoute, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agentic_rag.agent.state import ResearchStatus
from agentic_rag.api.schemas import ResearchRequest, ResearchResponse
from agentic_rag.api.service import ResearchService

METRICS_PATH: Final = "/metrics"
"""Where the exposition is served. Unversioned: it is operations, not the API contract."""

METRICS_STATE_KEY: Final = "metrics"
"""Attribute on ``app.state`` holding the registry every request is counted in."""

METRICS_CONTENT_TYPE: Final = "text/plain; version=0.0.4; charset=utf-8"
"""The content type Prometheus expects from a scrape target."""

UNKNOWN_PATH: Final = "other"
"""Label used for any request that did not match a route this application declares."""


def _label(value: str) -> str:
    """Return ``value`` escaped for use inside a Prometheus label."""
    return value.replace("\\", r"\\").replace('"', r"\"").replace("\n", r"\n")


class MetricsRegistry:
    """The counters one application process has recorded since it started.

    Guarded by a lock because FastAPI runs this service's synchronous endpoints in a
    worker thread, so two requests genuinely increment at the same time.
    """

    def __init__(self) -> None:
        """Start every counter at zero."""
        self._lock = threading.Lock()
        self._requests: Counter[tuple[str, str, int]] = Counter()
        self._runs: Counter[str] = Counter()
        self._steps_used = 0

    def record_request(self, *, method: str, path: str, status: int) -> None:
        """Count one served request.

        Args:
            method: HTTP method of the request.
            path: Route the request matched, or :data:`UNKNOWN_PATH`.
            status: HTTP status code of the response.
        """
        with self._lock:
            self._requests[(method, path, status)] += 1

    def record_run(self, *, status: ResearchStatus, steps_used: int) -> None:
        """Count one finished research run and the steps it spent.

        Args:
            status: Terminal status the run reported.
            steps_used: Retrieval steps the run actually spent.
        """
        with self._lock:
            self._runs[status.value] += 1
            self._steps_used += steps_used

    def render(self) -> str:
        """Return the current counters in the Prometheus text exposition format.

        Returns:
            The exposition, ending in a newline. Families with no samples yet still
            carry their ``HELP`` and ``TYPE`` lines, so a dashboard built against a
            fresh process does not have to wait for the first request to see the name.
        """
        with self._lock:
            requests = sorted(self._requests.items())
            runs = sorted(self._runs.items())
            steps_used = self._steps_used

        lines = [
            "# HELP process_up 1 while this process is serving.",
            "# TYPE process_up gauge",
            "process_up 1",
            "# HELP requests_total HTTP requests served, by method, route and status.",
            "# TYPE requests_total counter",
        ]
        lines += [
            f'requests_total{{method="{_label(method)}",path="{_label(path)}",'
            f'status="{status}"}} {count}'
            for (method, path, status), count in requests
        ]
        lines += [
            "# HELP research_total Research runs finished, by terminal status.",
            "# TYPE research_total counter",
        ]
        lines += [
            f'research_total{{status="{_label(status)}"}} {count}' for status, count in runs
        ]
        lines += [
            "# HELP research_steps_used_total Retrieval steps spent across all finished runs.",
            "# TYPE research_steps_used_total counter",
            f"research_steps_used_total {steps_used}",
        ]
        return "\n".join(lines) + "\n"


def get_registry(request: Request) -> MetricsRegistry:
    """Return the registry this application was built with.

    Args:
        request: The incoming request.

    Returns:
        The application's registry.

    Raises:
        RuntimeError: The application was built without one, which is a wiring defect.
    """
    registry = getattr(request.app.state, METRICS_STATE_KEY, None)
    if isinstance(registry, MetricsRegistry):
        return registry
    raise RuntimeError("the application was built without a metrics registry")


def run_and_count(
    request: Request,
    service: ResearchService,
    payload: ResearchRequest,
    *,
    request_id: str,
) -> ResearchResponse:
    """Perform one run through the service and count how it ended.

    Every way into the loop — the JSON route, the trace export, and both browser
    posts — goes through here, so a run that is served is a run that is counted and
    there is no fourth place for that to drift.

    Args:
        request: The incoming request, read for the application's registry.
        service: The application's research service.
        payload: The validated request.
        request_id: Correlation id established for this request.

    Returns:
        The finished run, correlated to ``request_id``.
    """
    response = service.run(payload, request_id=request_id)
    get_registry(request).record_run(status=response.status, steps_used=response.steps_used)
    return response


def declared_paths(
    route_groups: Sequence[Sequence[BaseRoute]], *, mounts: Sequence[str]
) -> tuple[frozenset[str], tuple[str, ...]]:
    """Return the exact routes and the mount prefixes an application declares.

    The routers are read directly rather than through ``app.routes``: FastAPI resolves an
    included router lazily, so the application's own table is not a list of routes at the
    moment the factory finishes building it.

    Args:
        route_groups: Routing tables to read — the application's own, and each router's.
        mounts: Prefixes served by a mount, counted under the prefix rather than per file.

    Returns:
        The set of exact paths, and the mount prefixes ordered longest first so the most
        specific mount wins when two of them nest.
    """
    exact = {
        route.path
        for group in route_groups
        for route in group
        if isinstance(route, Route)
    }
    return frozenset(exact), tuple(sorted(mounts, key=len, reverse=True))


class MetricsMiddleware:
    """Count every response this application emits, under a bounded set of labels."""

    def __init__(
        self,
        app: ASGIApp,
        registry: MetricsRegistry,
        exact_paths: frozenset[str],
        mount_paths: tuple[str, ...],
    ) -> None:
        """Wrap ``app`` and pin the labels it is allowed to emit.

        Args:
            app: The application being wrapped.
            registry: Where the counts go.
            exact_paths: Routes this application declares, counted under their own name.
            mount_paths: Mount prefixes, counted under the prefix rather than per file.
        """
        self.app = app
        self._registry = registry
        self._exact = exact_paths
        self._mounts = mount_paths

    def _path_label(self, raw_path: str) -> str:
        """Return the bounded label for ``raw_path``."""
        if raw_path in self._exact:
            return raw_path
        for mount in self._mounts:
            if raw_path == mount or raw_path.startswith(f"{mount}/"):
                return mount
        return UNKNOWN_PATH

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Delegate, and count the status the response started with."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", ""))
        label = self._path_label(str(scope.get("path", "")))

        async def send_and_count(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Counted at the start of the response rather than after its body, so a
                # response that fails mid-stream is still counted with the status it
                # promised — and counted exactly once, since a response starts once.
                self._registry.record_request(
                    method=method, path=label, status=int(message["status"])
                )
            await send(message)

        await self.app(scope, receive, send_and_count)
