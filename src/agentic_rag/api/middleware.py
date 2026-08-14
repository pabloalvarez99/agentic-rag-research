"""Establishing the correlation id once, for every response the service emits.

Written as raw ASGI rather than on ``BaseHTTPMiddleware`` for one reason that matters
here: the id has to live in the request *scope*, so an exception handler running later
reads the same value that was already promised in the response header. ``scope["state"]``
is per request by construction — there is no module-level place for an id to be stored,
which is what makes two requests in flight unable to see each other's.

The header is applied with ``setdefault``: a handler that already set the id explicitly
keeps it, and everything else — ``/health``, the OpenAPI document, a 404 — gets it here.
"""

from __future__ import annotations

from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agentic_rag.api.request_id import REQUEST_ID_HEADER, resolve_request_id

REQUEST_ID_SCOPE_KEY: Final = "request_id"
"""Key the resolved id is stored under in ``scope['state']``."""


def request_id_of(scope: Scope) -> str | None:
    """Return the id established for this request, when the middleware has run.

    Args:
        scope: The ASGI scope of the request being handled.

    Returns:
        The correlation id, or ``None`` when nothing established one — which is a
        failure so early that no request state exists yet.
    """
    state = scope.get("state")
    if not isinstance(state, dict):
        return None
    stored = state.get(REQUEST_ID_SCOPE_KEY)
    return stored if isinstance(stored, str) else None


class RequestIdMiddleware:
    """Resolve one correlation id per request and echo it on the way out."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Establish the id, then delegate."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state[REQUEST_ID_SCOPE_KEY] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).setdefault(REQUEST_ID_HEADER, request_id)
            await send(message)

        await self.app(scope, receive, send_with_request_id)
