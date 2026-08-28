"""The source-agnostic unit of evidence.

The agent never learns where a piece of evidence came from. It sees an
Evidence record and a pointer back to the snapshot bytes that produced it.
Swapping X for Telegram, or Grok for a direct API, changes an adapter and
nothing downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .provenance import digest, from_iso, to_iso


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where an Evidence record came from, precisely enough to re-derive it."""

    snapshot_id: str
    payload_digest: str
    source_id: str
    adapter_version: str
    # Index of this item inside the parsed payload. With the digest above,
    # this pins the claim to an exact position in exact bytes.
    item_index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "payload_digest": self.payload_digest,
            "source_id": self.source_id,
            "adapter_version": self.adapter_version,
            "item_index": self.item_index,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Provenance":
        return cls(
            snapshot_id=d["snapshot_id"],
            payload_digest=d["payload_digest"],
            source_id=d["source_id"],
            adapter_version=d["adapter_version"],
            item_index=d["item_index"],
        )


@dataclass(frozen=True, slots=True)
class Evidence:
    """One observed utterance: a post, an article, a message.

    Deliberately thin. Interpretation (sentiment, conviction, urgency) is a
    downstream concern and is never baked into the observation itself --
    otherwise re-running the interpreter would silently rewrite history.
    """

    external_id: str  # stable id at the origin (post id, article guid)
    author: str  # handle, channel name, or outlet
    published_at: datetime | None  # None when the source does not state one
    text: str
    url: str | None
    provenance: Provenance
    # Adapter-specific extras kept verbatim. Never promoted into typed
    # fields by the adapter; downstream code opts in explicitly.
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def evidence_id(self) -> str:
        """Stable identity: same bytes at the same position => same id."""
        return digest(
            {
                "payload_digest": self.provenance.payload_digest,
                "item_index": self.provenance.item_index,
                "external_id": self.external_id,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "external_id": self.external_id,
            "author": self.author,
            "published_at": to_iso(self.published_at) if self.published_at else None,
            "text": self.text,
            "url": self.url,
            "provenance": self.provenance.to_dict(),
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Evidence":
        pub = d.get("published_at")
        return cls(
            external_id=d["external_id"],
            author=d["author"],
            published_at=from_iso(pub) if pub else None,
            text=d["text"],
            url=d.get("url"),
            provenance=Provenance.from_dict(d["provenance"]),
            extra=d.get("extra", {}),
        )
