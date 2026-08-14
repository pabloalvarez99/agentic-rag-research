"""The correlation id is kept when it is safe to keep, and replaced when it is not.

The unsafe cases here are the ones that do damage after the request is over: a newline
that forges a log line, a control character or an unbounded string reflected into a
response header. None of them is answered with an error — a bad header on a good request
loses the caller their correlation, not their answer.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from agentic_rag.api.request_id import (
    MAX_REQUEST_ID_CHARS,
    is_safe_request_id,
    new_request_id,
    resolve_request_id,
)

SAFE = [
    "3f1a2b4c-5d6e-7f80-9012-3456789abcde",
    "run-42",
    "trace_id.7",
    "01HZY8QK3M4N5P6Q7R8S9T0V1W",
    "service:worker-3.attempt_2",
    "a",
    "z" * MAX_REQUEST_ID_CHARS,
]

UNSAFE = [
    "",
    " ",
    "-leading-separator",
    "has space",
    "line\nbreak",
    "carriage\rreturn",
    "null\x00byte",
    "tab\tseparated",
    "<script>alert(1)</script>",
    "../../etc/passwd",
    "id;DROP TABLE runs",
    "%0d%0aSet-Cookie:+x=1",
    "unicode-é",
    "z" * (MAX_REQUEST_ID_CHARS + 1),
]


@pytest.mark.parametrize("value", SAFE)
def test_a_safe_caller_id_is_kept(value: str) -> None:
    assert is_safe_request_id(value)
    assert resolve_request_id(value) == value


@pytest.mark.parametrize("value", UNSAFE)
def test_an_unsafe_caller_id_is_replaced_and_never_echoed(value: str) -> None:
    assert not is_safe_request_id(value)

    resolved = resolve_request_id(value)

    assert resolved != value
    if value.strip():
        assert value.strip() not in resolved
    UUID(resolved)


def test_surrounding_whitespace_is_normalised_rather_than_rejected() -> None:
    assert resolve_request_id("  run-42  ") == "run-42"


def test_an_absent_header_mints_one() -> None:
    minted = resolve_request_id(None)

    UUID(minted)
    assert is_safe_request_id(minted)


def test_minted_ids_are_distinct() -> None:
    assert len({new_request_id() for _ in range(100)}) == 100
