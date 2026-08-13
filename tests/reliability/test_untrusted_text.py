"""Retrieved text is untrusted, and the report is somewhere it gets printed.

Master plan §13.6 says to treat retrieved text as untrusted, and the CLI that
arrives with M3 prints `report` to a terminal. A passage carrying an ANSI escape
would then rewrite the operator's screen, and one carrying a control character
could hide the rest of the finding it belongs to. Neither is exotic: both are
ordinary bytes in a document nobody sanitised on the way in.

Nothing here asks the synthesiser to *interpret* untrusted text. It asks that
printing a finding cannot do anything other than print.
"""

from __future__ import annotations

import pytest

from agentic_rag.agent import run_research
from agentic_rag.agent.synthesizer import synthesize
from agentic_rag.tools import FakeRetrievalBackend, Passage, RetrieveTool
from reliability.backends import corpus

CONTROL_TEXT = "Chunking \x1b[31msplits\x1b[0m a document\x07 and \x00hides\x08 the rest."

C0 = tuple(chr(code) for code in range(0x20)) + ("\x7f",)
C1 = tuple(chr(code) for code in range(0x80, 0xA0))


def passage(text: str) -> Passage:
    return Passage(chunk_id="ctrl-1", source_path="docs/ctrl.md", text=text, rank=1)


def test_a_finding_carries_no_control_character_from_the_passage() -> None:
    result = synthesize("chunking?", [passage(CONTROL_TEXT)])

    assert "\x1b" not in result.report
    assert not any(control in result.report for control in C0 if control != "\n")
    assert not any(control in result.report for control in C1)


def test_a_citation_snippet_is_the_text_that_was_printed() -> None:
    result = synthesize("chunking?", [passage(CONTROL_TEXT)])
    snippet = result.citations[0].snippet
    assert snippet is not None

    assert snippet in result.report
    assert "\x1b" not in snippet


def test_stripping_a_control_character_does_not_join_two_words() -> None:
    result = synthesize("chunking?", [passage("Chunking\x07splits a document.")])

    assert "Chunkingsplits" not in result.report
    assert "Chunking splits a document." in result.report


def test_ordinary_unicode_survives_untouched() -> None:
    text = "El reranking — 再ランキング — reordena la lista corta 🧭 en español, con ñ."
    result = synthesize("reranking?", [passage(text)])

    assert "再ランキング" in result.report
    assert "🧭" in result.report
    assert "ñ" in result.report
    assert "—" in result.report


@pytest.mark.parametrize("control", ["\x1b", "\x07", "\x00", "\x7f", "\x9b"])
def test_a_control_character_never_reaches_a_report_through_the_loop(control: str) -> None:
    documents = corpus(f"Chunking{control} splits a document into pieces.")

    state = run_research(
        "chunking?",
        tool=RetrieveTool(FakeRetrievalBackend(documents)),
        max_steps=2,
    )
    assert state.report is not None

    assert control not in state.report
    assert all(control not in (citation.snippet or "") for citation in state.citations)
