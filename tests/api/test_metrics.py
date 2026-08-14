"""``GET /metrics``: what an operator can scrape, and what it must never carry."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from agentic_rag.agent.state import ResearchStatus
from agentic_rag.api.metrics import METRICS_PATH, UNKNOWN_PATH, MetricsRegistry
from agentic_rag.api.routes import RESEARCH_PATH, TRACE_PATH
from agentic_rag.api.service import ResearchService
from agentic_rag.main import create_app

from .conftest import ANSWERABLE, OFF_CORPUS


@pytest.fixture
def client(offline_service: ResearchService) -> Iterator[TestClient]:
    """Serve the exposition over a service that cannot reach a network."""
    with TestClient(create_app(offline_service)) as running:
        yield running


def sample(text: str, name: str) -> float:
    """Return the single value of ``name``, which must appear exactly once."""
    matches = [
        line for line in text.splitlines() if line.startswith(name) and not line.startswith("#")
    ]
    assert len(matches) == 1, f"{name!r} matched {matches}"
    return float(matches[0].rsplit(" ", 1)[1])


def test_a_fresh_process_is_up_and_names_every_family(client: TestClient) -> None:
    response = client.get(METRICS_PATH)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert sample(response.text, "process_up") == 1
    for family in ("requests_total", "research_total", "research_steps_used_total"):
        # A dashboard built against a fresh process should not have to wait for traffic
        # to discover the name of the series it is graphing.
        assert f"# TYPE {family} counter" in response.text


def test_requests_are_counted_by_route_and_status(client: TestClient) -> None:
    client.get("/health")
    client.get("/health")
    client.post(RESEARCH_PATH, json={"question": ANSWERABLE, "max_steps": 4})

    text = client.get(METRICS_PATH).text

    assert sample(text, 'requests_total{method="GET",path="/health",status="200"}') == 2
    assert sample(text, f'requests_total{{method="POST",path="{RESEARCH_PATH}",status="200"}}') == 1


def test_a_failure_is_counted_under_the_status_it_answered_with(client: TestClient) -> None:
    client.post(RESEARCH_PATH, json={"question": ANSWERABLE, "max_steps": 999})

    text = client.get(METRICS_PATH).text

    assert sample(text, f'requests_total{{method="POST",path="{RESEARCH_PATH}",status="422"}}') == 1


def test_an_unknown_path_cannot_grow_the_label_set(client: TestClient) -> None:
    for suffix in ("a", "b", "c"):
        client.get(f"/wp-admin/{suffix}")

    text = client.get(METRICS_PATH).text

    assert "wp-admin" not in text
    assert sample(text, f'requests_total{{method="GET",path="{UNKNOWN_PATH}",status="404"}}') == 3


def test_static_files_are_counted_under_their_mount(client: TestClient) -> None:
    client.get("/static/app.css")

    text = client.get(METRICS_PATH).text

    assert sample(text, 'requests_total{method="GET",path="/static",status="200"}') == 1


def test_runs_are_counted_by_terminal_status(client: TestClient) -> None:
    client.post(RESEARCH_PATH, json={"question": ANSWERABLE, "max_steps": 4})
    client.post(RESEARCH_PATH, json={"question": OFF_CORPUS, "max_steps": 4})

    text = client.get(METRICS_PATH).text

    assert sample(text, 'research_total{status="done"}') == 1
    assert sample(text, 'research_total{status="refused"}') == 1


def test_every_way_into_the_loop_is_counted(client: TestClient) -> None:
    body = {"question": ANSWERABLE, "max_steps": 4}
    form = {"question": ANSWERABLE, "max_steps": "4"}

    client.post(RESEARCH_PATH, json=body)
    client.post(TRACE_PATH, json=body)
    client.post("/ui/research", data=form)
    client.post("/ui/trace.json", data=form)

    text = client.get(METRICS_PATH).text

    assert sample(text, 'research_total{status="done"}') == 4


def test_steps_used_accumulates_across_runs(client: TestClient) -> None:
    spent = 0
    for _ in range(2):
        run = client.post(RESEARCH_PATH, json={"question": ANSWERABLE, "max_steps": 4})
        spent += int(run.json()["steps_used"])

    assert spent > 0
    assert sample(client.get(METRICS_PATH).text, "research_steps_used_total") == spent


def test_the_exposition_carries_no_question_and_no_correlation_id(client: TestClient) -> None:
    client.post(
        RESEARCH_PATH,
        json={"question": ANSWERABLE, "max_steps": 4},
        headers={"X-Request-ID": "metrics-secret-42"},
    )

    text = client.get(METRICS_PATH).text

    assert ANSWERABLE not in text
    assert "metrics-secret-42" not in text


def test_two_applications_do_not_share_counters(offline_service: ResearchService) -> None:
    # create_app is a factory so tests do not share state; a module-level counter would
    # quietly undo that and make one test's total depend on which test ran before it.
    with TestClient(create_app(offline_service)) as first:
        first.get("/health")
        first.get("/health")
        with TestClient(create_app(offline_service)) as second:
            text = second.get(METRICS_PATH).text

    assert 'path="/health"' not in text


def test_the_registry_escapes_a_label_it_is_handed() -> None:
    registry = MetricsRegistry()
    registry.record_request(method='GE"T', path="/a\\b", status=200)
    registry.record_run(status=ResearchStatus.DONE, steps_used=3)

    text = registry.render()

    assert 'method="GE\\"T"' in text
    assert 'path="/a\\\\b"' in text
    assert sample(text, "research_steps_used_total") == 3


def test_the_exposition_is_documented(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert METRICS_PATH in schema["paths"]
