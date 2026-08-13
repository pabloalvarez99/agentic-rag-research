"""Validation of the one outbound URL this agent is allowed to dial.

The agent has exactly one outbound surface — the retrieval service — and the
address of that service is deployment configuration, never data. Everything in
this module exists to keep those two things apart:

* A research question is text to search for. It is never a URL, and no code path
  turns one into a request target. :class:`ServiceUrl` is built once, from the
  environment or from an explicit argument, before any question is asked.
* A URL that *is* configured still has to be one this process should dial.
  ``file:///etc/passwd`` and ``http://user:secret@host`` both parse; neither is
  a retrieval service, and the second one puts a credential in a place that ends
  up in logs, in exception text and in a proxy's access log.

So the type is a whitelist, not a sanitiser. It refuses what it does not
understand rather than repairing it, because a repaired URL is a URL nobody
audited: silently dropping a query string, or coercing a scheme, means the
address that was configured and the address that was dialled are different, and
the difference only surfaces during an incident.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urlsplit

ALLOWED_SCHEMES: Final = ("http", "https")
"""The only two schemes a retrieval service can speak.

Everything else — ``file``, ``ftp``, ``data``, ``gopher`` — is either a local
read dressed as a fetch or a protocol this client cannot talk. Rejecting them
by name is cheaper than reasoning about what httpx would do with each.
"""

MAX_URL_CHARS: Final = 2_048
"""Upper bound on a configured base URL.

Not a security boundary on its own; a bound that stops a malformed environment
variable from becoming a multi-kilobyte string repeated in every log line and
every error message.
"""

_FORBIDDEN_PATH_SEGMENTS: Final = frozenset({"..", "."})
"""Relative segments a base URL may not carry.

A base URL is a prefix that other paths are appended to. ``http://host/api/..``
would make the resolved endpoint depend on how the server normalises, which is
a property of the server and not of this configuration.
"""


class InvalidServiceUrlError(ValueError):
    """A configured retrieval-service URL is not one this client will dial.

    ``ValueError`` rather than a tool error: this is raised while wiring the
    backend up, before any call exists to fail. A misconfigured address should
    stop the process that was misconfigured, not surface later as a retrieval
    that mysteriously found nothing.
    """


def _reject(raw: str, reason: str) -> InvalidServiceUrlError:
    """Build the error for *raw*, naming *reason* without echoing a credential.

    Args:
        raw: The URL as configured.
        reason: What is wrong with it, in the caller's terms.

    Returns:
        The error to raise. The URL is included only when it provably carries no
        userinfo, so an accidental ``https://user:token@host`` is never repeated
        into a log line by the very check that caught it.
    """
    shown = raw if "@" not in raw else "<redacted: url contains '@'>"
    return InvalidServiceUrlError(f"{shown}: {reason}")


class ServiceUrl:
    """A validated ``http``/``https`` base URL, and safe joining onto it.

    Built from a string once, at wiring time. Every property is derived from the
    parse that validated it, so there is no second interpretation of the same
    text later.
    """

    __slots__ = ("_base", "_host", "_scheme")

    def __init__(self, raw: str) -> None:
        """Validate *raw* and keep the normalised base.

        Normalisation is deliberately minimal: the scheme and host are
        lower-cased because both are case-insensitive by definition, and
        trailing slashes are dropped so joining is unambiguous. Nothing else is
        rewritten.

        Args:
            raw: Base URL of the retrieval service, e.g. ``http://127.0.0.1:8000``
                or ``https://rag.internal/api``.

        Raises:
            InvalidServiceUrlError: The value is empty, too long, carries control
                characters, uses a scheme other than ``http``/``https``, embeds
                credentials, names no host, carries a query or fragment, or has a
                relative path segment.
        """
        candidate = raw.strip()
        if not candidate:
            raise _reject(raw, "a retrieval service URL is required, and this one is empty")
        if len(candidate) > MAX_URL_CHARS:
            raise _reject(candidate[:64], f"longer than {MAX_URL_CHARS} characters")
        if any(character.isspace() or ord(character) < 0x20 for character in candidate):
            raise _reject(candidate, "contains whitespace or control characters")

        try:
            parts = urlsplit(candidate)
            port = parts.port
        except ValueError as error:  # malformed port, malformed IPv6 literal
            raise _reject(candidate, f"is not a parseable URL: {error}") from error

        scheme = parts.scheme.lower()
        if scheme not in ALLOWED_SCHEMES:
            allowed = " or ".join(f"{name}://" for name in ALLOWED_SCHEMES)
            raise _reject(candidate, f"must start with {allowed}, not {parts.scheme!r}")
        if parts.username is not None or parts.password is not None:
            raise _reject(candidate, "embeds credentials; put them in a header, not in a URL")
        if not parts.hostname:
            raise _reject(candidate, "names no host")
        if parts.query or parts.fragment:
            raise _reject(candidate, "carries a query string or fragment; give the base URL only")

        path = parts.path.rstrip("/")
        if any(segment in _FORBIDDEN_PATH_SEGMENTS for segment in path.split("/")):
            raise _reject(candidate, "contains a relative path segment ('.' or '..')")

        host = parts.hostname.lower()
        authority = f"{host}:{port}" if port is not None else host
        self._scheme = scheme
        self._host = host
        self._base = f"{scheme}://{authority}{path}"

    @property
    def base(self) -> str:
        """Return the normalised base URL, without a trailing slash."""
        return self._base

    @property
    def scheme(self) -> str:
        """Return the lower-cased scheme, always ``http`` or ``https``."""
        return self._scheme

    @property
    def host(self) -> str:
        """Return the lower-cased host, without the port."""
        return self._host

    def join(self, path: str) -> str:
        """Return ``base`` followed by *path*, with exactly one separator.

        Args:
            path: An absolute route on the service, e.g. ``/v1/query``. It is a
                constant from the upstream contract, never caller data, so it is
                appended rather than escaped.

        Returns:
            The fully qualified URL.

        Raises:
            ValueError: ``path`` is not absolute. A relative route joined onto a
                base with its own prefix silently resolves somewhere else, which
                is exactly the class of bug this type exists to prevent.
        """
        if not path.startswith("/"):
            raise ValueError(f"route must be absolute, got {path!r}")
        return f"{self._base}{path}"

    def __str__(self) -> str:
        """Return the normalised base URL."""
        return self._base

    def __repr__(self) -> str:
        """Return an unambiguous form for test output and tracebacks."""
        return f"ServiceUrl({self._base!r})"

    def __eq__(self, other: object) -> bool:
        """Compare on the normalised base, so equivalent spellings match."""
        if not isinstance(other, ServiceUrl):
            return NotImplemented
        return self._base == other._base

    def __hash__(self) -> int:
        """Hash the normalised base, keeping equality and hashing consistent."""
        return hash(self._base)
