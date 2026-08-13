"""The error envelope: one shape, stable slugs, and nothing leaked into the message.

The sanitisation tests are not cosmetic. A validation message is built from data the
caller controls — field names, and the validator's opinion of them — and it ends up in a
response body and in a log line. Unbounded length, control characters and echoed values
are the three ways that becomes a problem.
"""

from __future__ import annotations

from http import HTTPStatus

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentic_rag.api.errors import (
    MAX_REPORTED_FIELDS,
    BackendUnavailable,
    CapabilityMissing,
    ErrorResponse,
    ErrorType,
    RequestInvalid,
    RunNotReportable,
    RuntimeSurfaceError,
    describe_validation_errors,
)


class Narrow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=8)


def errors_of(payload: dict[str, object]) -> list[dict[str, object]]:
    with pytest.raises(ValidationError) as rejected:
        Narrow.model_validate(payload)
    return [dict(error) for error in rejected.value.errors()]


def test_every_deliberate_failure_carries_a_slug_and_a_status() -> None:
    failures: list[type[RuntimeSurfaceError]] = [
        RequestInvalid,
        CapabilityMissing,
        BackendUnavailable,
        RunNotReportable,
    ]

    for failure in failures:
        assert failure.error_type in ErrorType
        assert HTTPStatus(failure.http_status)


def test_the_slugs_are_the_ones_the_taxonomy_names() -> None:
    assert RequestInvalid.error_type is ErrorType.VALIDATION_ERROR
    assert CapabilityMissing.error_type is ErrorType.CAPABILITY_MISSING
    assert BackendUnavailable.error_type is ErrorType.BACKEND_UNAVAILABLE
    assert RunNotReportable.error_type is ErrorType.INTERNAL_ERROR


def test_a_defect_is_never_reported_as_a_provider_failure() -> None:
    assert RunNotReportable.error_type is not ErrorType.BACKEND_UNAVAILABLE
    assert RunNotReportable.http_status is HTTPStatus.INTERNAL_SERVER_ERROR


def test_a_failure_renders_as_the_shared_envelope() -> None:
    envelope = CapabilityMissing("no retrieval service is configured").as_response("run-42")

    assert envelope.model_dump() == {
        "error": "no retrieval service is configured",
        "error_type": "capability_missing",
        "request_id": "run-42",
    }


def test_the_envelope_allows_a_missing_correlation_id() -> None:
    assert ErrorResponse(error="x", error_type=ErrorType.INTERNAL_ERROR).request_id is None


def test_a_validation_message_names_the_field() -> None:
    message = describe_validation_errors(errors_of({"question": ""}))

    assert "question" in message
    assert message.startswith("the request is not valid: ")


def test_a_validation_message_does_not_echo_the_rejected_value() -> None:
    secret = "sk-not-a-real-key-0123456789"
    message = describe_validation_errors(errors_of({"question": secret}))

    assert secret not in message


def test_an_unknown_field_name_is_reported_without_its_control_characters() -> None:
    forged = "field\nWARNING: injected log line"
    message = describe_validation_errors(errors_of({"question": "q", forged: 1}))

    assert "\n" not in message
    assert "injected log line" in message


def test_a_long_field_name_is_cut() -> None:
    message = describe_validation_errors(errors_of({"question": "q", "f" * 500: 1}))

    assert len(message) < 400
    assert "..." in message


def test_only_the_first_few_problems_are_listed_and_the_rest_are_counted() -> None:
    payload: dict[str, object] = {f"extra_{index}": index for index in range(12)}
    payload["question"] = ""

    message = describe_validation_errors(errors_of(payload))

    assert message.count(";") == MAX_REPORTED_FIELDS
    assert "more problem(s)" in message


def test_an_empty_error_list_still_produces_a_sentence() -> None:
    assert describe_validation_errors([]) == "the request could not be validated"
