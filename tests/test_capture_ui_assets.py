"""The committed UI evidence and the script that rebuilds it stay in step.

Nothing here launches a browser: CI consumes the captures, it does not rebuild
them. What is checked is the part that silently rots — a renamed capture, a
deleted PNG, or a README that points at a file nobody committed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "capture_ui.py"
ASSETS = ROOT / "docs" / "assets"
DOCUMENTS = (ROOT / "README.md", ROOT / "docs" / "SHIP.md", ROOT / "docs" / "CASESTUDY.md")


def _load_capture_module() -> ModuleType:
    """Import ``scripts/capture_ui.py`` by path, since ``scripts`` is not a package."""
    spec = importlib.util.spec_from_file_location("capture_ui", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves the script's postponed annotations through sys.modules,
    # so the module has to be registered before its body runs.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return module


@pytest.fixture(scope="module")
def capture_ui() -> ModuleType:
    return _load_capture_module()


def test_capture_script_imports_without_playwright(capture_ui: ModuleType) -> None:
    # Playwright is a [docs] extra. Importing the script must not require it, or the
    # module becomes untestable on exactly the installs CI uses.
    assert capture_ui.CAPTURES
    assert {entry.name for entry in capture_ui.CAPTURES} == {"ui-done", "ui-trace", "ui-budget"}


def test_captures_are_pinned_to_the_free_path(capture_ui: ModuleType) -> None:
    assert capture_ui.BASE_URL == "http://127.0.0.1:8010"
    assert capture_ui.VIEWPORT == {"width": 1280, "height": 1000}
    for entry in capture_ui.CAPTURES:
        # A fixed correlation id is what makes two runs byte-identical.
        assert entry.request_id == entry.name.replace("ui-", "capture-ui-")


def test_documented_outcomes_cover_an_answer_and_a_spent_budget(capture_ui: ModuleType) -> None:
    outcomes = {entry.name: entry.outcome for entry in capture_ui.CAPTURES}
    assert outcomes["ui-done"] == "done"
    assert outcomes["ui-budget"] == "budget_exhausted"


def test_every_declared_capture_is_committed(capture_ui: ModuleType) -> None:
    for entry in capture_ui.CAPTURES:
        path = ASSETS / f"{entry.name}.png"
        assert path.is_file(), f"missing capture: run python scripts/capture_ui.py ({path})"
        assert path.stat().st_size > 0


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: path.name)
def test_referenced_captures_exist(document: Path) -> None:
    # A README that embeds docs/assets/ui-*.png must not outlive the file it points at.
    text = document.read_text(encoding="utf-8")
    for name in ("ui-done", "ui-trace", "ui-budget"):
        if f"assets/{name}.png" in text:
            assert (ASSETS / f"{name}.png").is_file()
