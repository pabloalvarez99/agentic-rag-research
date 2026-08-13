"""The CLI: what it prints, where it prints it, and what it exits with.

Most cases drive ``main()`` directly with explicit streams, which is what makes them
fast and lets them inject a service. Two cases run the real interpreter in a subprocess,
because ``python -m agentic_rag.research`` working from a foreign working directory and
writing encodable bytes to a real console are properties that an in-process call cannot
observe.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_rag.agent.state import ResearchStatus
from agentic_rag.api.errors import ErrorType
from agentic_rag.api.schemas import MAX_MAX_STEPS, MAX_QUESTION_CHARS, MAX_TOP_K
from agentic_rag.api.service import ResearchService
from agentic_rag.research import (
    EXIT_BACKEND_UNAVAILABLE,
    EXIT_CAPABILITY_MISSING,
    EXIT_INTERNAL,
    EXIT_NO_ANSWER,
    EXIT_OK,
    EXIT_USAGE,
    main,
)
from agentic_rag.tools.base import ToolError
from agentic_rag.tools.retrieve import PRODUCTION_RAG_URL_ENV

from .conftest import ANSWERABLE, OFF_CORPUS, RecordingFactory, StubRunner, build_state

THIN = "How does chunking work?"
RESPONSE_FIELDS = {"status", "report", "citations", "steps_used", "trace", "request_id"}
ERROR_FIELDS = {"error", "error_type", "request_id"}


class Run:
    """One CLI invocation: its exit code and both of its streams."""

    def __init__(self, code: int, stdout: str, stderr: str) -> None:
        self.code = code
        self.stdout = stdout
        self.stderr = stderr

    @property
    def payload(self) -> dict[str, Any]:
        parsed: dict[str, Any] = json.loads(self.stdout)
        return parsed

    @property
    def lines(self) -> list[str]:
        return self.stdout.splitlines()


def run_cli(*argv: str, service: ResearchService | None = None) -> Run:
    """Run the CLI in process with captured streams."""
    stdout, stderr = io.StringIO(), io.StringIO()
    offline = ResearchService(retriever_factory=RecordingFactory()) if service is None else service
    code = main(list(argv), service=offline, stdout=stdout, stderr=stderr)
    return Run(code, stdout.getvalue(), stderr.getvalue())


# --- stdout discipline ---------------------------------------------------------------


def test_stdout_is_exactly_one_json_object() -> None:
    run = run_cli("--question", ANSWERABLE)

    assert len(run.lines) == 1
    assert set(run.payload) == RESPONSE_FIELDS


def test_the_last_stdout_line_is_json_for_a_failure_too() -> None:
    run = run_cli("--question", "", service=ResearchService(retriever_factory=RecordingFactory()))

    assert len(run.lines) == 1
    assert set(run.payload) == ERROR_FIELDS


def test_the_human_summary_goes_to_stderr_and_never_to_stdout() -> None:
    run = run_cli("--question", ANSWERABLE)

    assert "status=" in run.stderr
    assert "status=" not in run.stdout.split('"status"')[0]
    assert run.stderr.strip().count("\n") == 0


def test_the_summary_never_repeats_the_question() -> None:
    question = "What does hybrid retrieval buy over dense retrieval alone?"
    run = run_cli("--question", question)

    assert question not in run.stderr


def test_quiet_silences_stderr_and_leaves_stdout_alone() -> None:
    loud = run_cli("--question", ANSWERABLE)
    quiet = run_cli("--question", ANSWERABLE, "--quiet")

    assert quiet.stderr == ""
    assert quiet.payload["report"] == loud.payload["report"]


def test_the_summary_reports_the_shape_of_the_run() -> None:
    run = run_cli("--question", ANSWERABLE)

    for field in ("status=", "steps_used=", "citations=", "retriever=fake", "request_id="):
        assert field in run.stderr


# --- exit codes ----------------------------------------------------------------------


def test_a_grounded_answer_exits_zero() -> None:
    run = run_cli("--question", ANSWERABLE)

    assert run.code == EXIT_OK
    assert run.payload["status"] == ResearchStatus.DONE.value


def test_a_refusal_exits_one_and_still_prints_the_report() -> None:
    run = run_cli("--question", OFF_CORPUS, "--max-steps", "3")

    assert run.code == EXIT_NO_ANSWER
    assert run.payload["status"] == ResearchStatus.REFUSED.value
    assert "Refused" in run.payload["report"]
    assert run.payload["trace"]


def test_an_exhausted_budget_exits_one_and_prints_what_it_grounded() -> None:
    run = run_cli("--question", THIN, "--max-steps", "1", "--top-k", "1")

    assert run.code == EXIT_NO_ANSWER
    assert run.payload["status"] == ResearchStatus.BUDGET_EXHAUSTED.value
    assert run.payload["citations"]


def test_a_degraded_run_exits_one() -> None:
    service = ResearchService(
        runner=StubRunner(state=build_state(status=ResearchStatus.DEGRADED)),
        retriever_factory=RecordingFactory(),
    )
    run = run_cli("--question", ANSWERABLE, service=service)

    assert run.code == EXIT_NO_ANSWER


def test_a_missing_question_is_a_usage_error() -> None:
    run = run_cli()

    assert run.code == EXIT_USAGE
    assert run.payload["error_type"] == ErrorType.VALIDATION_ERROR.value


def test_an_unknown_flag_is_a_usage_error() -> None:
    run = run_cli("--question", ANSWERABLE, "--temperature", "0.7")

    assert run.code == EXIT_USAGE
    assert set(run.payload) == ERROR_FIELDS


def test_a_non_integer_bound_is_a_usage_error() -> None:
    run = run_cli("--question", ANSWERABLE, "--max-steps", "three")

    assert run.code == EXIT_USAGE


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--max-steps", str(MAX_MAX_STEPS + 1)),
        ("--max-steps", "0"),
        ("--top-k", str(MAX_TOP_K + 1)),
        ("--top-k", "0"),
    ],
)
def test_a_bound_outside_the_contract_is_a_usage_error(flag: str, value: str) -> None:
    run = run_cli("--question", ANSWERABLE, flag, value)

    assert run.code == EXIT_USAGE
    assert run.payload["error_type"] == ErrorType.VALIDATION_ERROR.value


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_question_is_a_usage_error(blank: str) -> None:
    assert run_cli("--question", blank).code == EXIT_USAGE


def test_an_oversized_question_is_a_usage_error() -> None:
    assert run_cli("--question", "q" * (MAX_QUESTION_CHARS + 1)).code == EXIT_USAGE


def test_the_boundaries_themselves_are_accepted() -> None:
    assert run_cli("--question", ANSWERABLE, "--max-steps", str(MAX_MAX_STEPS)).code == EXIT_OK
    assert run_cli("--question", ANSWERABLE, "--top-k", str(MAX_TOP_K)).code == EXIT_OK


def test_an_unconfigured_http_retriever_has_its_own_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PRODUCTION_RAG_URL_ENV, raising=False)
    run = run_cli("--question", ANSWERABLE, "--retriever", "http", service=ResearchService())

    assert run.code == EXIT_CAPABILITY_MISSING
    assert run.payload["error_type"] == ErrorType.CAPABILITY_MISSING.value
    assert PRODUCTION_RAG_URL_ENV in run.payload["error"]


def test_an_unconfigured_http_retriever_does_not_fall_back_to_the_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PRODUCTION_RAG_URL_ENV, raising=False)
    run = run_cli("--question", ANSWERABLE, "--retriever", "http", service=ResearchService())

    assert set(run.payload) == ERROR_FIELDS
    assert "report" not in run.payload


def test_a_failing_backend_has_its_own_exit_code() -> None:
    leaked = "http://127.0.0.1:9/v1/query did not answer: connection refused"
    service = ResearchService(
        runner=StubRunner(error=ToolError(leaked)),
        retriever_factory=RecordingFactory(),
    )
    run = run_cli("--question", ANSWERABLE, service=service)

    assert run.code == EXIT_BACKEND_UNAVAILABLE
    assert leaked not in run.stdout
    assert "127.0.0.1" not in run.stdout


def test_a_defect_exits_five_and_still_leaves_parsable_stdout() -> None:
    service = ResearchService(
        runner=StubRunner(error=ZeroDivisionError("a defect in this program")),
        retriever_factory=RecordingFactory(),
    )
    run = run_cli("--question", ANSWERABLE, service=service)

    assert run.code == EXIT_INTERNAL
    assert run.payload["error_type"] == ErrorType.INTERNAL_ERROR.value
    assert "a defect in this program" not in run.stdout
    assert "Traceback" in run.stderr


def test_every_documented_exit_code_is_distinct() -> None:
    codes = [
        EXIT_OK,
        EXIT_NO_ANSWER,
        EXIT_USAGE,
        EXIT_CAPABILITY_MISSING,
        EXIT_BACKEND_UNAVAILABLE,
        EXIT_INTERNAL,
    ]

    assert len(set(codes)) == len(codes)


# --- arguments, quoting and Unicode ---------------------------------------------------


def test_a_question_with_quotes_and_apostrophes_survives() -> None:
    question = "Why does 'hybrid' retrieval beat \"dense-only\" search?"
    run = run_cli("--question", question)

    assert question in run.payload["report"]


@pytest.mark.parametrize(
    "question",
    [
        "¿Por qué usar citas en RAG?",
        "为什么在 RAG 中使用引用?",
        "Why cite? 🤔",
        "naïve café résumé",
        "Ключевые слова",
    ],
)
def test_a_unicode_question_round_trips_through_ascii_json(question: str) -> None:
    run = run_cli("--question", question)

    assert run.stdout.isascii()
    assert question in run.payload["report"]


def test_a_question_with_a_newline_is_preserved_in_the_json() -> None:
    question = "First part\nsecond part"
    run = run_cli("--question", question)

    assert len(run.lines) == 1
    assert question in run.payload["report"]


def test_the_short_flag_is_the_same_as_the_long_one() -> None:
    assert run_cli("-q", ANSWERABLE).payload["status"] == run_cli(
        "--question", ANSWERABLE
    ).payload["status"]


def test_a_caller_request_id_is_carried_into_the_output() -> None:
    run = run_cli("--question", ANSWERABLE, "--request-id", "batch-7")

    assert run.payload["request_id"] == "batch-7"
    assert "batch-7" in run.stderr


def test_an_unsafe_request_id_is_replaced() -> None:
    run = run_cli("--question", ANSWERABLE, "--request-id", "batch 7\ninjected")

    assert run.payload["request_id"] != "batch 7\ninjected"
    assert "injected" not in run.stdout


def test_help_exits_zero_without_printing_json(capsys: pytest.CaptureFixture[str]) -> None:
    stdout, stderr = io.StringIO(), io.StringIO()

    code = main(["--help"], stdout=stdout, stderr=stderr)

    assert code == EXIT_OK
    assert stdout.getvalue() == ""
    assert "exit codes:" in capsys.readouterr().out


# --- determinism ----------------------------------------------------------------------


def test_two_identical_runs_differ_only_in_their_request_id() -> None:
    first = run_cli("--question", ANSWERABLE).payload
    second = run_cli("--question", ANSWERABLE).payload

    assert first.pop("request_id") != second.pop("request_id")
    assert first == second


# --- the real interpreter -------------------------------------------------------------


def module_run(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the CLI as a module in a subprocess, from ``cwd``."""
    return subprocess.run(
        [sys.executable, "-m", "agentic_rag.research", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        check=False,
        env={"PATH": "", "SYSTEMROOT": "C:\\Windows"},
    )


def test_the_module_runs_from_a_directory_that_is_not_the_repository(tmp_path: Path) -> None:
    completed = module_run("--question", ANSWERABLE, cwd=tmp_path)

    payload = json.loads(completed.stdout)
    assert completed.returncode == EXIT_OK
    assert set(payload) == RESPONSE_FIELDS
    assert payload["status"] == ResearchStatus.DONE.value


def test_the_brief_smoke_command_produces_one_parsable_line(tmp_path: Path) -> None:
    completed = module_run(
        "--question", "Why use citations in RAG?", "--max-steps", "3", "--retriever", "fake",
        cwd=tmp_path,
    )

    assert len(completed.stdout.splitlines()) == 1
    payload = json.loads(completed.stdout)
    assert payload["status"] in {status.value for status in ResearchStatus}
    assert completed.returncode in {EXIT_OK, EXIT_NO_ANSWER}
