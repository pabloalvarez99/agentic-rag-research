r"""Rebuild the credential-free UI evidence in ``docs/assets``.

Run ``pip install -e \".[docs]\" && playwright install chromium`` once, then
``python scripts/capture_ui.py``. The script starts this repository's own
application on the deterministic fake retriever, drives the server-rendered form
in a headless browser, and writes one PNG per documented outcome.

Nothing here contacts a provider. ``PRODUCTION_RAG_URL`` is cleared in the child
environment and the UI form pins ``retriever=fake``, so the captures cannot show
a hosted result even on a machine that has one configured.

Two runs of this script produce byte-identical PNGs: the viewport is pinned, the
questions are fixed, the loop is deterministic, and the one value that would
otherwise vary — the correlation id — is supplied per capture through
``X-Request-ID``, which the service echoes when it is safe to echo. Pass
``--verify`` to re-capture into a temporary directory and compare SHA-256
digests against the committed files instead of overwriting them.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
HOST = "127.0.0.1"
PORT = 8010
BASE_URL = f"http://{HOST}:{PORT}"
VIEWPORT = {"width": 1280, "height": 1000}


@dataclass(frozen=True)
class Capture:
    """One documented UI outcome and the run that produces it.

    Attributes:
        name: File stem written under ``docs/assets``.
        question: Question typed into the form, verbatim.
        max_steps: Retrieval budget the form is set to.
        outcome: Terminal status the rendered page must carry, asserted before
            the screenshot so a changed loop fails the capture instead of
            quietly publishing a different outcome.
        request_id: Correlation id sent as ``X-Request-ID``, so the visible id is
            fixed rather than a fresh UUID on every run.
        trace_open: Whether the trace timeline is expanded. Collapsing it on the
            answer capture keeps the report, the citations and the request id in
            one readable frame; the trace has its own capture.
    """

    name: str
    question: str
    max_steps: int
    outcome: str
    request_id: str
    trace_open: bool


CAPTURES: tuple[Capture, ...] = (
    Capture(
        name="ui-done",
        question="How does reciprocal rank fusion score a document?",
        max_steps=4,
        outcome="done",
        request_id="capture-ui-done",
        trace_open=False,
    ),
    Capture(
        name="ui-trace",
        question=(
            "Which vendor supplied the Reykjavik diesel generators, and then how does "
            "reciprocal rank fusion combine two rankings into one?"
        ),
        max_steps=4,
        outcome="done",
        request_id="capture-ui-trace",
        trace_open=True,
    ),
    Capture(
        name="ui-budget",
        question=(
            "How much did the Melbourne trampoline franchise pay in royalties, and then "
            "what does a cross-encoder reranker do with the shortlist it reads?"
        ),
        max_steps=1,
        outcome="budget_exhausted",
        request_id="capture-ui-budget",
        trace_open=True,
    ),
)
"""The committed evidence: a grounded answer, a multi-step trace, and a run the budget ended."""


def _target(capture: Capture, directory: Path) -> Path:
    """Return where ``capture`` is written inside ``directory``."""
    return directory / f"{capture.name}.png"


def _free_port_or_fail() -> None:
    """Raise when the capture port is already in use.

    A server left running from a previous session would be captured instead of
    the one this script configures, which is how a credentialed instance ends up
    in a screenshot that claims to be credential-free.
    """
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex((HOST, PORT)) == 0:
            raise RuntimeError(
                f"{BASE_URL} is already serving; stop it so the capture owns the process"
            )


def _wait_for_api(process: subprocess.Popen[bytes], timeout: float = 60.0) -> None:
    """Block until the application answers ``/health`` or the wait runs out.

    Args:
        process: The uvicorn process being waited on.
        timeout: Seconds to wait before giving up.

    Raises:
        RuntimeError: The process exited, or it never became healthy.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"the API exited with code {process.returncode} before serving")
        try:
            with urllib.request.urlopen(f"{BASE_URL}/health", timeout=2) as response:  # noqa: S310
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"API did not become healthy within {timeout:.0f} seconds")


def _start_api() -> subprocess.Popen[bytes]:
    """Start uvicorn on the free path and return the running process."""
    env = os.environ.copy()
    env["PRODUCTION_RAG_URL"] = ""
    return subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "uvicorn",
            "agentic_rag.main:app",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _submit(page: Page, capture: Capture) -> None:
    """Fill the form for ``capture``, submit it, and wait for the expected outcome.

    Raises:
        RuntimeError: The rendered page carries a different terminal status than
            the capture declares.
    """
    page.goto(BASE_URL, wait_until="networkidle")
    page.locator("#question").fill(capture.question)
    page.locator("#max_steps").fill(str(capture.max_steps))
    with page.expect_navigation(wait_until="networkidle"):
        page.get_by_role("button", name="Run research").click()
    if page.locator(f".outcome-{capture.outcome}").count() != 1:
        rendered = page.locator(".run-stats dd").first.text_content()
        raise RuntimeError(
            f"{capture.name}: expected status {capture.outcome!r}, page rendered {rendered!r}"
        )
    page.locator("details.trace").evaluate(
        "(node, open) => { node.open = open; }", capture.trace_open
    )


def _screenshot(page: Page, capture: Capture, directory: Path) -> Path:
    """Write ``capture`` as a full-page PNG in ``directory`` and return the path."""
    path = _target(capture, directory)
    page.screenshot(path=path, full_page=True, animations="disabled", caret="hide")
    return path


def _digest(path: Path) -> str:
    """Return the SHA-256 of ``path``."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _capture_all(directory: Path) -> None:
    """Run every documented outcome once and write its PNG into ``directory``.

    Raises:
        RuntimeError: Playwright is not installed, or a run did not render the
            outcome its capture declares.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            'Playwright is documentation-only; install it with pip install -e ".[docs]"'
        ) from exc

    _free_port_or_fail()
    directory.mkdir(parents=True, exist_ok=True)
    api = _start_api()
    try:
        _wait_for_api(api)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for capture in CAPTURES:
                    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
                    context.set_extra_http_headers({"X-Request-ID": capture.request_id})
                    page = context.new_page()
                    _submit(page, capture)
                    _screenshot(page, capture, directory)
                    context.close()
            finally:
                browser.close()
    finally:
        api.terminate()
        api.wait(timeout=10)


def capture() -> None:
    """Rebuild the committed captures in ``docs/assets`` and print their digests."""
    _capture_all(ASSETS)
    for entry in CAPTURES:
        path = _target(entry, ASSETS)
        print(f"{entry.name}: {_digest(path)}  {path.relative_to(ROOT)}")


def verify() -> None:
    """Re-capture into a temporary directory and compare against the committed PNGs.

    Raises:
        RuntimeError: A committed capture is missing or its digest changed.
    """
    missing = [entry.name for entry in CAPTURES if not _target(entry, ASSETS).is_file()]
    if missing:
        raise RuntimeError(f"committed captures are missing: {', '.join(missing)}")

    drifted: list[str] = []
    with TemporaryDirectory() as workspace:
        directory = Path(workspace)
        _capture_all(directory)
        for entry in CAPTURES:
            committed = _digest(_target(entry, ASSETS))
            rebuilt = _digest(_target(entry, directory))
            marker = "ok" if committed == rebuilt else "DRIFT"
            print(f"{entry.name}: {marker} committed={committed} rebuilt={rebuilt}")
            if committed != rebuilt:
                drifted.append(entry.name)
    if drifted:
        raise RuntimeError(f"captures no longer reproduce: {', '.join(drifted)}")


def main() -> int:
    """Parse CLI arguments and return a process exit code."""
    parser = argparse.ArgumentParser(description="Rebuild or verify the committed UI captures.")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="re-capture into a temporary directory and compare digests instead of overwriting",
    )
    args = parser.parse_args()
    try:
        if args.verify:
            verify()
        else:
            capture()
    except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
        print(f"capture failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
