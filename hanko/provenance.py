"""Canonical serialisation and content addressing.

Every claim the agent makes must trace back to bytes it actually received.
That guarantee rests on two primitives defined here:

  canonical_json  -- one, and only one, byte representation per value
  digest          -- content address derived from those bytes

If canonical_json is not stable, replay is not stable, and the reasoning
trail stops being evidence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Status(str, Enum):
    """Outcome of a fetch, recorded rather than inferred.

    DEGRADED and FAILED are stored exactly like OK. A source that dropped
    is a fact about the world, not an error to swallow.
    """

    OK = "ok"
    DEGRADED = "degraded"  # answered, but incompletely (rate limited, truncated)
    FAILED = "failed"  # no usable answer at all


class Coverage(str, Enum):
    """How much of the requested window the response actually covers."""

    COMPLETE = "complete"  # source guarantees the full window
    PARTIAL = "partial"  # known to be missing some of the window
    UNKNOWN = "unknown"  # search-style source; recall cannot be established


def canonical_json(value: Any) -> bytes:
    """Serialise to the one byte string this project treats as canonical."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    """Content address of a JSON-serialisable value."""
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def digest_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    """RFC3339 in UTC, always with an explicit offset."""
    if dt.tzinfo is None:
        raise ValueError("refusing to serialise a naive datetime")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def from_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
