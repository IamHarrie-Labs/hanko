"""The source adapter contract.

One rule governs this whole package:

    fetch() touches the network and is allowed to be non-deterministic.
    parse() touches nothing and MUST be a pure function of its payload.

Everything the agent reasons over comes out of parse(). Because parse() is
pure and the payload is content-addressed, any decision can be replayed
from stored bytes and must reach the same verdict. Put a network call in
parse() and the reasoning trail stops being reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..evidence import Evidence
from ..provenance import Coverage, Status


class PayloadShapeError(RuntimeError):
    """parse() was handed bytes it does not know how to read.

    Raised rather than returning an empty list. "I cannot read this" and
    "there was nothing here" are different facts, and collapsing them
    would let a schema change look like a quiet market.
    """


@dataclass(frozen=True, slots=True)
class Query:
    """What was asked for. Part of the snapshot key, so it must be canonical."""

    subjects: tuple[str, ...]  # handles, channel ids, feed urls
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 50
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..provenance import to_iso

        return {
            "subjects": list(self.subjects),
            "since": to_iso(self.since) if self.since else None,
            "until": to_iso(self.until) if self.until else None,
            "limit": self.limit,
            "options": self.options,
        }


@dataclass(frozen=True, slots=True)
class RawResponse:
    """The unmodified result of one fetch, plus how well it went.

    `payload` is stored verbatim. Adapters must not clean, reshape, or
    fill it -- a payload that has been tidied is no longer evidence of
    what the source actually said.
    """

    payload: Any
    status: Status
    coverage: Coverage
    # Populated whenever status is not OK. Free-form but always present
    # as a human-readable explanation of what went wrong.
    error: str | None = None
    # Anything the adapter learned about the call that is not part of the
    # payload: http status, rate-limit headers, token usage, cost.
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Source(Protocol):
    """A place evidence comes from."""

    source_id: str
    adapter_version: str

    def fetch(self, query: Query) -> RawResponse:
        """Impure. Network, clocks, rate limits, failure."""
        ...

    def parse(self, payload: Any) -> list[dict[str, Any]]:
        """Pure. Payload -> ordered list of normalised item dicts.

        Returns plain dicts rather than Evidence because provenance
        (snapshot id, digest) is not known until the payload has been
        stored. The store attaches it. Order must be stable: item_index
        is part of every evidence identity.

        Expected keys per item: external_id, author, published_at
        (datetime | None), text, url, extra.
        """
        ...


def bind_provenance(
    items: list[dict[str, Any]],
    *,
    snapshot_id: str,
    payload_digest: str,
    source_id: str,
    adapter_version: str,
) -> list[Evidence]:
    """Attach provenance to parsed items, pinning each to its exact position."""
    from ..evidence import Provenance

    out: list[Evidence] = []
    for index, item in enumerate(items):
        out.append(
            Evidence(
                external_id=item["external_id"],
                author=item["author"],
                published_at=item.get("published_at"),
                text=item["text"],
                url=item.get("url"),
                extra=item.get("extra", {}),
                provenance=Provenance(
                    snapshot_id=snapshot_id,
                    payload_digest=payload_digest,
                    source_id=source_id,
                    adapter_version=adapter_version,
                    item_index=index,
                ),
            )
        )
    return out
