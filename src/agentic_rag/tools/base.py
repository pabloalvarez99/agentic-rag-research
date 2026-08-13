"""The structural contract every agent tool satisfies.

A tool is a named, described callable with a typed request and a typed result.
The contract is a ``Protocol`` rather than a base class on purpose: the loop has
to hold a retriever built here, a stub written inside a test, and a planner that
does not exist yet, without any of them inheriting behaviour they do not use or
registering with something at import time.

``description`` is part of the contract because it is what a planner reads when
it picks the next step. A tool described at the call site is a tool that can be
described two different ways in two different places, and the plan is built from
whichever copy the planner happened to see.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class ToolError(RuntimeError):
    """A tool could not produce a result.

    Raised for failures that belong to the tool: an unreachable dependency, a
    response it cannot parse. Invalid input is not one of these — the request
    model rejects it before the tool runs. Neither is an empty result: finding
    no evidence is an outcome the loop has to reason about, not an error that
    unwinds it.
    """


@runtime_checkable
class Tool[RequestT, ResultT](Protocol):
    """One step the agent can take.

    ``name`` and ``description`` are declared read-only, so an implementation
    may satisfy them with a plain class attribute and does not have to write a
    property to be a tool.
    """

    @property
    def name(self) -> str:
        """Return the stable identifier a plan and a trace refer to."""

    @property
    def description(self) -> str:
        """Return what the tool does, and the boundary it does not cross."""

    def run(self, request: RequestT) -> ResultT:
        """Execute the tool once.

        Args:
            request: Validated input for this call.

        Returns:
            The result of the call, including the empty one.

        Raises:
            ToolError: The tool could not produce a result at all.
        """
