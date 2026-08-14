"""Experiment pack round-trip: two runs + compare + policy + hash."""

from __future__ import annotations

from pathlib import Path

from agentic_rag.agent import run_research
from agentic_rag.api.runs import RunArtifact
from agentic_rag.pack import ExperimentPack, PackPolicy
from agentic_rag.tools import FakeRetrievalBackend, RetrieveTool


def _artifact(question: str, request_id: str, *, max_steps: int = 4) -> RunArtifact:
    state = run_research(
        question,
        tool=RetrieveTool(FakeRetrievalBackend()),
        max_steps=max_steps,
    )
    return RunArtifact.from_state(state, request_id=request_id, retriever="fake")


def test_pack_round_trip_dir_and_zip(tmp_path: Path) -> None:
    left = _artifact("How does reciprocal rank fusion score a document?", "pack-left")
    right = _artifact("Who won the 2099 Antarctic chess championship?", "pack-right")
    pack = ExperimentPack.build(
        left,
        right,
        policy=PackPolicy(
            retriever="fake",
            max_steps=4,
            max_calls={"retrieve": 4},
            season_tag="v1.0",
            billed=False,
        ),
    )
    assert pack.compare.identical is False
    assert pack.manifest.pack_hash
    assert len(pack.experiments) == 2

    directory = pack.write_dir(tmp_path / "pack")
    loaded = ExperimentPack.load_dir(directory)
    assert loaded.manifest.pack_hash == pack.manifest.pack_hash
    assert loaded.compare.model_dump() == pack.compare.model_dump()

    zipped = pack.to_zip_bytes()
    from_zip = ExperimentPack.load_zip(zipped)
    assert from_zip.manifest.pack_hash == pack.manifest.pack_hash


def test_identical_runs_produce_empty_compare_diffs() -> None:
    left = _artifact("How does reciprocal rank fusion score a document?", "same-a")
    # Free-path is deterministic: compared fields match even when request_id differs.
    right = _artifact("How does reciprocal rank fusion score a document?", "same-b")
    pack = ExperimentPack.build(left, right)
    assert pack.compare.identical is True
    assert pack.compare.diffs == ()
