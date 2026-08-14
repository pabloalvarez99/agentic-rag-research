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

from typing import Final, Protocol, runtime_checkable

ERROR_TOOL: Final = "tool_error"
"""Fallback slug: a tool failed and said nothing more specific."""

ERROR_BACKEND_UNAVAILABLE: Final = "backend_unavailable"
"""The dependency could not be reached, or did not answer in time."""

ERROR_PROVIDER: Final = "provider_error"
"""The dependency was reached and failed while doing its work."""

ERROR_UNAUTHORIZED: Final = "unauthorized"
"""The dependency requires a credential this process does not send."""

ERROR_RATE_LIMITED: Final = "rate_limited"
"""The dependency is shedding load from this client."""

ERROR_VALIDATION: Final = "validation_error"
"""The dependency rejected what was sent to it."""

ERROR_CONTRACT_MISMATCH: Final = "contract_mismatch"
"""The dependency answered, and the answer is not the contract it publishes.

The one slug in this set with no entry in the portfolio-wide failure taxonomy,
because it names a failure only a *client* can observe: the difference between
"the service is broken" and "the service is fine and no longer the service this
code was written against" is invisible from the inside, and collapsing it into
``provider_error`` sends whoever is on call to read the wrong logs.
"""


class ToolError(RuntimeError):
    """A tool could not produce a result.

    Raised for failures that belong to the tool: an unreachable dependency, a
    response it cannot parse. Invalid input is not one of these — the request
    model rejects it before the tool runs. Neither is an empty result: finding
    no evidence is an outcome the loop has to reason about, not an error that
    unwinds it.

    ``error_type`` is a stable slug, carried so a caller can branch on the class
    of failure and a report can group by it without parsing a message. The
    message is what a human reads and is free to be rewritten; the slug is what a
    dashboard counts and is not. The default keeps every existing raise site
    valid, so a tool that has nothing more specific to say still says something.
    """

    def __init__(self, message: str, *, error_type: str = ERROR_TOOL) -> None:
        """Record the message and the stable slug that classifies it.

        Args:
            message: What went wrong, for a human. Never carries a credential.
            error_type: Stable machine-readable class of failure.
        """
        super().__init__(message)
        self.error_type = error_type


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
