"""The record a run keeps of a tool call that could not produce a result.

A tool talks to something outside the process, so it eventually fails, and the
loop has to write that down. The question this module answers is *what* it is
allowed to write down.

Not the exception. :class:`~agentic_rag.tools.base.ToolError` messages are built
from what the backend saw:
:class:`~agentic_rag.tools.retrieve.HttpRetrievalBackend` interpolates its query
URL and the transport error, and a base URL is exactly the kind of string that
carries a credential (``https://user:token@host``). A body it could not parse is
untrusted text from another service. Copying any of that into the state would put
it in the report, in the trace, in whatever the API serialises, and in every log
that touches one of them.

So :func:`tool_failure` takes a tool name and nothing else. There is no argument
through which provider text could reach a :class:`ToolFailure`, which is a
stronger guarantee than a redaction pass over a message: nothing has to be
matched correctly for it to hold.

The cost is that the cause is not in the state. The cause belongs to the
observability layer, which binds a request id and masks what it writes; that
layer arrives with the HTTP route. Until then, a failed run says *that* the tool
failed, honestly, and the operator's own logs say why.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolFailureType = Literal["tool_error"]
"""Stable slugs for why a tool produced nothing.

One member, because one is what the tool contract distinguishes today: a tool
either produced a result or raised ``ToolError``. A tool layer that later tells a
timeout apart from an unreadable body adds a member here, and a consumer that
switched on ``"tool_error"`` keeps working.
"""

TOOL_ERROR: Final[ToolFailureType] = "tool_error"
"""The failure type recorded for any ``ToolError`` a tool call raises."""


class ToolFailure(BaseModel):
    """A tool call that raised, as much of it as is safe to keep.

    ``detail`` is generated here rather than taken from the exception, and it is
    the same sentence the report prints and the trace records — one string in
    both places, so a reader can check the report against the trace instead of
    comparing two paraphrases of the same event.
    """

    model_config = ConfigDict(frozen=True)

    tool: str = Field(min_length=1, description="Name of the tool whose call failed.")
    error_type: ToolFailureType = Field(description="Stable slug for the kind of failure.")
    detail: str = Field(min_length=1, description="What happened, in words safe to publish.")


def tool_failure(tool: str) -> ToolFailure:
    """Return the failure record for a tool call that raised ``ToolError``.

    Args:
        tool: Name of the tool that failed. The only input, deliberately — see
            the module docstring.

    Returns:
        A typed failure carrying no text that came from the tool or its backend.
    """
    return ToolFailure(
        tool=tool,
        error_type=TOOL_ERROR,
        detail=f"the {tool!r} tool could not produce a result",
    )
