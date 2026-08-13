"""The evidence value type every retrieval backend returns.

It lives beside the backends rather than beside the tool because a passage is
what a *retriever* produces: the tool is the loop-facing surface and has no
reason to own the shape. Keeping it here is also what lets the P1 adapter and
the retrieve tool import it without importing each other, which is the only
reason the two can live in separate modules at all.

``agentic_rag.tools.retrieve`` re-exports it, so every existing import keeps
working and no caller has to learn where it moved.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Passage(BaseModel):
    """One retrieved chunk of evidence, with the identity needed to cite it.

    Text, a stable chunk id and a corpus-relative source path are the three
    fields a citation needs to be checkable by someone who does not trust the
    agent. Frozen, because a passage is what a backend returned: evidence that
    can be edited afterwards is evidence a citation cannot be checked against.

    ``source_path`` is carried verbatim and is never resolved, opened or joined
    against a local directory. It arrives from a retrieval service over the
    network, so treating it as a filesystem path would turn a hostile corpus
    into a file read; it is an identifier a human uses to find the source, and
    nothing more.
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=1, description="Stable identifier of the supporting chunk.")
    source_path: str = Field(description="Corpus-relative path of the document it came from.")
    text: str = Field(description="Passage text exactly as the backend returned it.")
    rank: int = Field(ge=1, description="Position of the passage in the ranking it arrived in.")
    title: str | None = Field(default=None, description="Source document title, when known.")
    heading_path: str | None = Field(
        default=None,
        description="Heading ancestry within the source document, when known.",
    )
