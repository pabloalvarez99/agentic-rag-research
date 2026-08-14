"""Opt-in gate for the tests that need a real production-rag instance.

Everything in this directory talks to a running service. That makes it the one
part of the suite that can fail for reasons which have nothing to do with this
repository — a container that did not start, a corpus that was never ingested, a
port already taken — so it does not run unless someone asks for it, twice:

* ``RUN_P1_INTEGRATION=1`` — the deliberate opt-in.
* ``PRODUCTION_RAG_URL`` — the instance to talk to.

Both are required, and requiring two is not belt-and-braces. ``PRODUCTION_RAG_URL``
is the same variable that switches the *agent* onto the hosted backend, so a
developer who exports it to run the agent against a local stack has not thereby
volunteered their test suite for network access. The opt-in is the second
variable, which nothing else reads.

Absent either one, these tests are skipped with the reason printed, which is what
keeps CI green on a machine with no Docker without anyone editing a config file.
The contract and mock-transport suites under ``tests/contracts`` cover the same
adapter offline and never skip; this directory only adds the evidence that the
service on the other side still behaves the way those mocks claim.
"""

from __future__ import annotations

import os

import pytest

RUN_ENV = "RUN_P1_INTEGRATION"
URL_ENV = "PRODUCTION_RAG_URL"

SKIP_REASON = (
    f"opt-in: set {RUN_ENV}=1 and {URL_ENV}=http://127.0.0.1:8000 with a "
    "production-rag demo stack running (scripts/integration/verify_p1.ps1 does both)"
)


def pytest_configure(config: pytest.Config) -> None:
    """Register the marker here, because pyproject.toml belongs to another lane."""
    config.addinivalue_line(
        "markers",
        "integration: needs a running production-rag instance; opt in with "
        f"{RUN_ENV}=1 and {URL_ENV}",
    )


def opted_in() -> bool:
    """Return whether both the opt-in and the address are present."""
    return os.environ.get(RUN_ENV, "").strip() == "1" and bool(
        os.environ.get(URL_ENV, "").strip()
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip every integration test unless the run was opted into explicitly."""
    if opted_in():
        return
    skip = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def base_url() -> str:
    """Return the address of the instance under test."""
    return os.environ[URL_ENV].strip()
