"""Source adapters and the registry that resolves them at replay time.

Replay needs to find the adapter that captured a snapshot, using only the
source_id stored in the envelope. The registry is that lookup.
"""

from __future__ import annotations

from typing import Callable

from .base import (
    PayloadShapeError,
    Query,
    RawResponse,
    Source,
    bind_provenance,
)
from .fixture import FixtureSource
from .rss import RssSource
from .xsearch import XSearchSource

_BUILDERS: dict[str, Callable[[], Source]] = {
    "rss": RssSource,
    "x": XSearchSource,
}


def register(source_id: str, builder: Callable[[], Source]) -> None:
    _BUILDERS[source_id] = builder


def resolve(source_id: str) -> Source:
    """Build the adapter for a stored source_id.

    Raises rather than substituting a stand-in: replaying a snapshot with
    the wrong adapter would produce evidence that was never observed.
    """
    if source_id.startswith("ryo:"):
        # Tool sources are constructed by name rather than registered one
        # by one, so a snapshot from any of the seven replays the same way.
        from ..ryotools.client import RyoToolSource

        return RyoToolSource(source_id.removeprefix("ryo:"))

    if source_id not in _BUILDERS:
        raise KeyError(
            "no adapter registered for source_id " + repr(source_id)
            + "; known: " + ", ".join(sorted(_BUILDERS))
        )
    return _BUILDERS[source_id]()


__all__ = [
    "FixtureSource",
    "PayloadShapeError",
    "Query",
    "RawResponse",
    "RssSource",
    "Source",
    "XSearchSource",
    "bind_provenance",
    "register",
    "resolve",
]
