"""Fixture adapter: a source backed by a local JSON file.

Two jobs.

  Development is free. Collect real snapshots once, then build and debug
  against them without spending another call or waiting on a rate limit.

  Tests are honest. Every failure mode a live source can produce --
  degraded, empty, rate limited, malformed -- is a fixture file, so the
  agent's behaviour under a dropped dependency is covered by CI rather
  than demonstrated by hope.

Fixture file shape:

    {
      "status": "ok" | "degraded" | "failed",
      "coverage": "complete" | "partial" | "unknown",
      "error": null,
      "items": [ {external_id, author, published_at, text, url, extra} ]
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..provenance import Coverage, Status, from_iso
from .base import Query, RawResponse


class FixtureSource:
    adapter_version = "1.0.0"

    def __init__(self, path: str | Path | None, source_id: str = "fixture") -> None:
        # None is valid here: replay only ever calls parse() on a stored
        # payload, never fetch(), so a FixtureSource resolved purely for
        # replay has no file to point at and does not need one.
        self.path = Path(path) if path is not None else None
        self.source_id = source_id

    def fetch(self, query: Query) -> RawResponse:
        if self.path is None:
            raise ValueError("FixtureSource has no path to fetch; resolved for replay only")
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        status = Status(doc.get("status", "ok"))
        return RawResponse(
            payload=None if status is Status.FAILED else doc,
            status=status,
            coverage=Coverage(doc.get("coverage", "unknown")),
            error=doc.get("error"),
            meta={"fixture": self.path.name},
        )

    def parse(self, payload: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for raw in payload.get("items", []):
            published = raw.get("published_at")
            items.append(
                {
                    "external_id": str(raw["external_id"]),
                    "author": str(raw["author"]),
                    "published_at": from_iso(published) if published else None,
                    "text": raw.get("text", ""),
                    "url": raw.get("url"),
                    "extra": raw.get("extra", {}),
                }
            )
        # Fixture order is authored deliberately, so it is preserved as-is.
        return items
