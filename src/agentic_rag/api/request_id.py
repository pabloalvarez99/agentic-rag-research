"""The correlation id: one per request, echoed, never trusted as it arrives.

A request id exists so a line in this service's log can be joined to a line in the
caller's log and to a run's trace. That is only useful if the id survives the hop, so a
caller-supplied ``X-Request-ID`` is kept — and only useful if it is *safe*, because the
id is written into logs and reflected in a response header, which are the two places a
hostile string does damage:

* a newline in a logged id forges a second log line, which is how an audit trail stops
  being evidence;
* a control character or an unbounded string reflected into a header is the caller
  choosing what this service emits.

So the rule is **validate, then keep or replace** — never reject. A malformed header on
an otherwise perfect request is not worth a 400: the caller loses their correlation and
gets an answer, which is the proportionate outcome. A rejected request would only trade
one broken trail for a broken call.
"""

from __future__ import annotations

import re
from typing import Final
from uuid import uuid4

REQUEST_ID_HEADER: Final = "X-Request-ID"
"""Header this service reads and echoes."""

MAX_REQUEST_ID_CHARS: Final = 128
"""Longest caller id kept. Enough for a UUID, a ULID, or a traceparent-shaped id."""

_SAFE_REQUEST_ID: Final = re.compile(rf"[A-Za-z0-9][A-Za-z0-9._:-]{{0,{MAX_REQUEST_ID_CHARS - 1}}}")
"""Alphanumerics plus the four separators correlation ids are actually written with."""


def new_request_id() -> str:
    """Return a fresh correlation id."""
    return str(uuid4())


def is_safe_request_id(value: str) -> bool:
    """Return whether ``value`` may be echoed into a log line and a response header.

    Args:
        value: A candidate id, usually a caller-supplied header.

    Returns:
        ``True`` when the whole string matches the accepted character set and length.
    """
    return _SAFE_REQUEST_ID.fullmatch(value) is not None


def resolve_request_id(value: str | None) -> str:
    """Return the caller's id when it is safe to echo, otherwise a fresh one.

    Args:
        value: The raw header value, or ``None`` when the caller sent none.

    Returns:
        Either ``value`` trimmed of surrounding whitespace, or a newly minted id. Never
        empty, and never a string this service would not have produced itself.
    """
    if value is not None:
        candidate = value.strip()
        if is_safe_request_id(candidate):
            return candidate
    return new_request_id()
