"""Experiment packs: two run payloads + compare diff + policy + manifest.

Files remain the source of truth after serverless recycle. A pack is a directory
(or zip) a reviewer can load without resolving server ids (docs/SEASON.md Month 3).
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentic_rag.api.compare import CompareResponse, compare_runs
from agentic_rag.api.runs import RunArtifact
from agentic_rag.experiment import ExperimentRecord, pack_bytes_hash

PACK_SCHEMA_VERSION: Final = "1.0"
MANIFEST_NAME: Final = "manifest.json"
POLICY_NAME: Final = "policy.json"
RUN_A_NAME: Final = "run_a.json"
RUN_B_NAME: Final = "run_b.json"
COMPARE_NAME: Final = "compare.json"
EXPERIMENTS_NAME: Final = "experiments.jsonl"


class PackPolicy(BaseModel):
    """Budgets and tool caps that governed the packed runs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    retriever: str = "fake"
    max_steps: int = Field(ge=1, le=20)
    max_calls: dict[str, int] = Field(default_factory=dict)
    season_tag: str = "v1.0"
    billed: bool = False


class PackManifest(BaseModel):
    """Top-level pack identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = PACK_SCHEMA_VERSION
    pack_hash: str
    left_id: str
    right_id: str
    experiment_ids: tuple[str, ...] = ()


class ExperimentPack(BaseModel):
    """In-memory experiment pack ready to serialize or load into the UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: PackPolicy
    left: RunArtifact
    right: RunArtifact
    compare: CompareResponse
    experiments: tuple[ExperimentRecord, ...] = ()
    manifest: PackManifest

    @classmethod
    def build(
        cls,
        left: RunArtifact,
        right: RunArtifact,
        *,
        policy: PackPolicy | None = None,
        experiments: tuple[ExperimentRecord, ...] | None = None,
    ) -> Self:
        """Build a pack from two finished-run payloads and recompute compare."""
        diff = compare_runs(left, right)
        pol = policy or PackPolicy(
            retriever=left.retriever,
            max_steps=max(left.max_steps, right.max_steps),
            max_calls={"retrieve": max(left.max_steps, right.max_steps)},
            billed=False,
        )
        exps = experiments
        if exps is None:
            exps = (
                ExperimentRecord.from_run_artifact(left),
                ExperimentRecord.from_run_artifact(right),
            )
        raw = _canonical_payload(pol, left, right, diff, exps)
        digest = pack_bytes_hash(raw)
        manifest = PackManifest(
            pack_hash=digest,
            left_id=left.request_id,
            right_id=right.request_id,
            experiment_ids=tuple(exp.id for exp in exps),
        )
        # Re-hash with manifest pack_hash field fixed: hash content without circularity
        # by hashing policy+runs+compare+experiments only (see _canonical_payload).
        return cls(
            policy=pol,
            left=left,
            right=right,
            compare=diff,
            experiments=exps,
            manifest=manifest,
        )

    def write_dir(self, directory: Path) -> Path:
        """Write pack files into ``directory``; return the directory."""
        directory.mkdir(parents=True, exist_ok=True)
        (directory / POLICY_NAME).write_text(
            self.policy.model_dump_json(indent=2), encoding="utf-8"
        )
        (directory / RUN_A_NAME).write_text(
            self.left.model_dump_json(indent=2), encoding="utf-8"
        )
        (directory / RUN_B_NAME).write_text(
            self.right.model_dump_json(indent=2), encoding="utf-8"
        )
        (directory / COMPARE_NAME).write_text(
            self.compare.model_dump_json(indent=2), encoding="utf-8"
        )
        (directory / MANIFEST_NAME).write_text(
            self.manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        lines = [exp.model_dump_json() for exp in self.experiments]
        (directory / EXPERIMENTS_NAME).write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )
        return directory

    def to_zip_bytes(self) -> bytes:
        """Return a zip archive of the pack files."""
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(POLICY_NAME, self.policy.model_dump_json(indent=2))
            archive.writestr(RUN_A_NAME, self.left.model_dump_json(indent=2))
            archive.writestr(RUN_B_NAME, self.right.model_dump_json(indent=2))
            archive.writestr(COMPARE_NAME, self.compare.model_dump_json(indent=2))
            archive.writestr(MANIFEST_NAME, self.manifest.model_dump_json(indent=2))
            lines = [exp.model_dump_json() for exp in self.experiments]
            archive.writestr(
                EXPERIMENTS_NAME, "\n".join(lines) + ("\n" if lines else "")
            )
        return buffer.getvalue()

    @classmethod
    def load_dir(cls, directory: Path) -> Self:
        """Load and validate a pack directory; recompute compare must match stored."""
        policy = PackPolicy.model_validate_json(
            (directory / POLICY_NAME).read_text(encoding="utf-8")
        )
        left = RunArtifact.model_validate_json(
            (directory / RUN_A_NAME).read_text(encoding="utf-8")
        )
        right = RunArtifact.model_validate_json(
            (directory / RUN_B_NAME).read_text(encoding="utf-8")
        )
        stored_compare = CompareResponse.model_validate_json(
            (directory / COMPARE_NAME).read_text(encoding="utf-8")
        )
        manifest = PackManifest.model_validate_json(
            (directory / MANIFEST_NAME).read_text(encoding="utf-8")
        )
        experiments: list[ExperimentRecord] = []
        exp_path = directory / EXPERIMENTS_NAME
        if exp_path.is_file():
            for line in exp_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    experiments.append(ExperimentRecord.model_validate_json(line))
        recomputed = compare_runs(left, right)
        if recomputed.model_dump(mode="json") != stored_compare.model_dump(mode="json"):
            raise ValueError("stored compare.json does not match recomputed payload diff")
        raw = _canonical_payload(policy, left, right, stored_compare, tuple(experiments))
        digest = pack_bytes_hash(raw)
        if digest != manifest.pack_hash:
            raise ValueError(
                f"pack_hash mismatch: manifest={manifest.pack_hash!r} computed={digest!r}"
            )
        return cls(
            policy=policy,
            left=left,
            right=right,
            compare=stored_compare,
            experiments=tuple(experiments),
            manifest=manifest,
        )

    @classmethod
    def load_zip(cls, data: bytes) -> Self:
        """Load a pack from zip bytes via a temporary extract of required members."""
        with zipfile.ZipFile(BytesIO(data), "r") as archive:
            required = {MANIFEST_NAME, POLICY_NAME, RUN_A_NAME, RUN_B_NAME, COMPARE_NAME}
            names = set(archive.namelist())
            missing = required - names
            if missing:
                raise ValueError(f"pack zip missing files: {sorted(missing)}")
            # Write to a temp layout in memory via nested validate
            policy = PackPolicy.model_validate_json(archive.read(POLICY_NAME))
            left = RunArtifact.model_validate_json(archive.read(RUN_A_NAME))
            right = RunArtifact.model_validate_json(archive.read(RUN_B_NAME))
            stored_compare = CompareResponse.model_validate_json(archive.read(COMPARE_NAME))
            manifest = PackManifest.model_validate_json(archive.read(MANIFEST_NAME))
            experiments: list[ExperimentRecord] = []
            if EXPERIMENTS_NAME in names:
                for line in archive.read(EXPERIMENTS_NAME).decode("utf-8").splitlines():
                    if line.strip():
                        experiments.append(ExperimentRecord.model_validate_json(line))
            recomputed = compare_runs(left, right)
            if recomputed.model_dump(mode="json") != stored_compare.model_dump(mode="json"):
                raise ValueError("stored compare.json does not match recomputed payload diff")
            raw = _canonical_payload(policy, left, right, stored_compare, tuple(experiments))
            digest = pack_bytes_hash(raw)
            if digest != manifest.pack_hash:
                raise ValueError(
                    f"pack_hash mismatch: manifest={manifest.pack_hash!r} computed={digest!r}"
                )
            return cls(
                policy=policy,
                left=left,
                right=right,
                compare=stored_compare,
                experiments=tuple(experiments),
                manifest=manifest,
            )


class PackLoadRequest(BaseModel):
    """API body: either inline JSON parts or a base64 zip (UI uses inline parts)."""

    model_config = ConfigDict(extra="forbid")

    policy: PackPolicy
    left: RunArtifact
    right: RunArtifact
    compare: CompareResponse | None = None
    experiments: list[ExperimentRecord] = Field(default_factory=list)

    @field_validator("experiments", mode="before")
    @classmethod
    def _none_experiments(
        cls, value: list[ExperimentRecord] | None
    ) -> list[ExperimentRecord]:
        return value if value is not None else []


def _canonical_payload(
    policy: PackPolicy,
    left: RunArtifact,
    right: RunArtifact,
    compare: CompareResponse,
    experiments: tuple[ExperimentRecord, ...],
) -> bytes:
    """Byte-stable payload used for pack_hash (excludes the hash itself)."""
    document = {
        "policy": policy.model_dump(mode="json"),
        "left": left.model_dump(mode="json"),
        "right": right.model_dump(mode="json"),
        "compare": compare.model_dump(mode="json"),
        "experiments": [exp.model_dump(mode="json") for exp in experiments],
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


__all__ = [
    "COMPARE_NAME",
    "EXPERIMENTS_NAME",
    "ExperimentPack",
    "MANIFEST_NAME",
    "PACK_SCHEMA_VERSION",
    "POLICY_NAME",
    "PackLoadRequest",
    "PackManifest",
    "PackPolicy",
    "RUN_A_NAME",
    "RUN_B_NAME",
]
