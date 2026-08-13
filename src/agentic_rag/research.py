"""``python -m agentic_rag.research`` — the command-line door into the same loop.

The CLI and ``POST /v1/research`` are two doors into one room. Both build a
:class:`~agentic_rag.api.schemas.ResearchRequest`, both hand it to
:class:`~agentic_rag.api.service.ResearchService`, and both render what comes back with
the same models. A test asserts the two produce identical JSON for the same question,
which is the only durable way to keep them from drifting: a CLI that reimplements a
route is a second answer to what the agent does, and the second one is always the one
that is out of date.

Three rules govern the output, and each exists because a machine reads it:

* **stdout is exactly one JSON object.** Success prints the run; a typed failure prints
  the same error envelope the HTTP route returns. Nothing else is ever written there, so
  ``... | jq .status`` needs no filter and "the last line is JSON" holds by construction
  rather than by convention.
* **Everything a human reads goes to stderr**, and can be silenced with ``--quiet``. The
  summary carries the status, the steps, the citation count, the backend and the request
  id — and never the question, because a CLI that echoes the prompt into a terminal log
  is the same mistake as a service that logs prompts by default.
* **The JSON is ASCII.** ``ensure_ascii`` means the output encodes on any console —
  which matters on Windows, where stdout is not UTF-8 by default — and a non-ASCII
  question still round-trips exactly through ``json.loads``.

Exit codes are a contract, documented in ``--help`` and in
``docs/workstreams/a1-runtime-surface.md``. A run that refused exits non-zero: the
question a script asks is "did I get a grounded answer?", and the answer is no. The
report, its gaps and the full trace are still printed — a refusal is an outcome, not an
error, and the exit code is the only place that distinction is compressed.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections.abc import Sequence
from typing import IO, Final

from pydantic import ValidationError

from agentic_rag.agent.state import DEFAULT_MAX_STEPS, ResearchStatus
from agentic_rag.api.errors import (
    ErrorResponse,
    ErrorType,
    RequestInvalid,
    RuntimeSurfaceError,
    describe_validation_errors,
)
from agentic_rag.api.request_id import resolve_request_id
from agentic_rag.api.schemas import ResearchRequest, ResearchResponse, RetrieverChoice
from agentic_rag.api.service import ResearchService
from agentic_rag.tools.retrieve import DEFAULT_TOP_K

PROGRAM = "python -m agentic_rag.research"

EXIT_OK: Final = 0
"""The run finished ``done``: a grounded report with citations."""

EXIT_NO_ANSWER: Final = 1
"""The run finished without a grounded answer: refused, budget exhausted, degraded."""

EXIT_USAGE: Final = 2
"""The arguments were wrong. Argparse's own code, kept rather than renumbered."""

EXIT_CAPABILITY_MISSING: Final = 3
"""A retriever was requested that this installation is not configured to serve."""

EXIT_BACKEND_UNAVAILABLE: Final = 4
"""A configured backend failed the call."""

EXIT_INTERNAL: Final = 5
"""A defect in this program."""

EXIT_CODES: Final[dict[ErrorType, int]] = {
    ErrorType.VALIDATION_ERROR: EXIT_USAGE,
    ErrorType.CAPABILITY_MISSING: EXIT_CAPABILITY_MISSING,
    ErrorType.BACKEND_UNAVAILABLE: EXIT_BACKEND_UNAVAILABLE,
    ErrorType.INTERNAL_ERROR: EXIT_INTERNAL,
    ErrorType.NOT_FOUND: EXIT_INTERNAL,
    ErrorType.METHOD_NOT_ALLOWED: EXIT_INTERNAL,
    ErrorType.HTTP_ERROR: EXIT_INTERNAL,
}
"""Every slug the shared envelope can carry, mapped to the code that reports it."""

EPILOG = f"""
output:
  stdout is exactly one JSON object and nothing else: the finished run, or the
  {{"error", "error_type", "request_id"}} envelope the HTTP route uses. The
  human-readable summary goes to stderr; --quiet silences it.

exit codes:
  {EXIT_OK}  the run answered from evidence (status 'done')
  {EXIT_NO_ANSWER}  the run finished without a grounded answer (refused,
     budget_exhausted, degraded) - the report and its gaps are still printed
  {EXIT_USAGE}  usage error, or a question or bound outside its allowed range
  {EXIT_CAPABILITY_MISSING}  capability_missing: the chosen retriever is not configured here
  {EXIT_BACKEND_UNAVAILABLE}  backend_unavailable: a configured backend failed the call
  {EXIT_INTERNAL}  internal error in this program

The default retriever is a deterministic in-process fixture over a small committed
corpus. It exercises the loop with no credential and no network, and supports no
claim about retrieval or answer quality.
""".strip()


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser, with the exit-code contract in its help."""
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Run one bounded plan / retrieve / critique research loop.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--question",
        "-q",
        required=True,
        help="The research question. Required.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=DEFAULT_MAX_STEPS,
        help=f"Hard cap on tool calls (default: {DEFAULT_MAX_STEPS}).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"Passages one retrieval step may return (default: {DEFAULT_TOP_K}).",
    )
    parser.add_argument(
        "--retriever",
        choices=[choice.value for choice in RetrieverChoice],
        default=RetrieverChoice.FAKE.value,
        help=(
            "Retrieval backend. 'fake' is deterministic and contacts nothing; 'http' needs a "
            "configured production-rag instance and fails rather than falling back to 'fake' "
            f"(default: {RetrieverChoice.FAKE.value})."
        ),
    )
    parser.add_argument(
        "--request-id",
        default=None,
        help="Correlation id to record on this run. Minted when absent or unsafe.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human-readable summary on stderr. stdout is unaffected.",
    )
    return parser


def build_request(namespace: argparse.Namespace) -> ResearchRequest:
    """Return the validated request for parsed arguments.

    Args:
        namespace: What the parser produced.

    Returns:
        The same request model the HTTP route validates, so both doors enforce one
        contract rather than two that agree today.

    Raises:
        RequestInvalid: A value is outside the contract's bounds. Reported in the same
            envelope and with the same slug the route would use.
    """
    try:
        return ResearchRequest(
            question=namespace.question,
            max_steps=namespace.max_steps,
            top_k=namespace.top_k,
            retriever=RetrieverChoice(namespace.retriever),
        )
    except ValidationError as invalid:
        raise RequestInvalid(describe_validation_errors(invalid.errors())) from invalid


def exit_code_for(status: ResearchStatus) -> int:
    """Return the exit code a finished run reports.

    Args:
        status: The run's terminal status.

    Returns:
        :data:`EXIT_OK` for a grounded answer, :data:`EXIT_NO_ANSWER` for every other
        terminal status.
    """
    return EXIT_OK if status is ResearchStatus.DONE else EXIT_NO_ANSWER


def summarize(response: ResearchResponse, *, retriever: RetrieverChoice) -> str:
    """Return the one-line human summary written to stderr.

    It names the run's shape and never its content: no question, no report text. A
    terminal scrollback and a CI log are both places a prompt should not end up by
    default.
    """
    return (
        f"status={response.status.value} steps_used={response.steps_used} "
        f"citations={len(response.citations)} retriever={retriever.value} "
        f"request_id={response.request_id}"
    )


def emit(payload: ResearchResponse | ErrorResponse, stream: IO[str]) -> None:
    """Write ``payload`` as one line of ASCII JSON.

    ``ensure_ascii`` keeps the line encodable on a console that is not UTF-8, which is
    the default on Windows. A non-ASCII question survives it: the escapes decode back to
    the original string through ``json.loads``.
    """
    stream.write(json.dumps(payload.model_dump(mode="json"), ensure_ascii=True) + "\n")
    stream.flush()


def main(
    argv: Sequence[str] | None = None,
    *,
    service: ResearchService | None = None,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    """Run one research loop from the command line and return the exit code.

    Args:
        argv: Arguments without the program name. ``None`` reads ``sys.argv``.
        service: The service performing the run. Omitted, the default one is built —
            which is what makes a test able to drive this function without a network.
        stdout: Where the JSON goes. Defaults to the process's stdout.
        stderr: Where the summary goes. Defaults to the process's stderr.

    Returns:
        One of the documented exit codes. This function never raises for an expected
        failure; it prints the envelope and returns the code that names it.
    """
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr

    try:
        namespace = build_parser().parse_args(argv)
    except SystemExit as requested:
        # argparse writes its own diagnosis to stderr and exits. Intercepting it keeps
        # the promise that stdout carries one JSON object whatever happened — a promise
        # a caller can only rely on if it also holds for the arguments being wrong.
        code = requested.code if isinstance(requested.code, int) else EXIT_USAGE
        if code == EXIT_OK:  # --help and --version print to stdout and are not failures.
            return EXIT_OK
        emit(
            ErrorResponse(
                error="the command line arguments are not valid; see --help",
                error_type=ErrorType.VALIDATION_ERROR,
            ),
            out,
        )
        return EXIT_USAGE

    request_id = resolve_request_id(namespace.request_id)
    runner = ResearchService() if service is None else service

    try:
        request = build_request(namespace)
        response = runner.run(request, request_id=request_id)
    except RuntimeSurfaceError as failure:
        emit(failure.as_response(request_id), out)
        if not namespace.quiet:
            err.write(f"{failure.error_type.value}: {failure}\n")
        return EXIT_CODES[failure.error_type]
    except Exception:  # noqa: BLE001 - a defect must still leave parsable output
        # The traceback goes to stderr, where a developer reads it; stdout keeps its
        # single JSON object so a pipeline reading it does not receive a truncated
        # stream and a stack trace instead.
        traceback.print_exc(file=err)
        emit(
            ErrorResponse(
                error="the command failed to complete the run",
                error_type=ErrorType.INTERNAL_ERROR,
                request_id=request_id,
            ),
            out,
        )
        return EXIT_INTERNAL

    emit(response, out)
    if not namespace.quiet:
        err.write(summarize(response, retriever=request.retriever) + "\n")
    return exit_code_for(response.status)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
