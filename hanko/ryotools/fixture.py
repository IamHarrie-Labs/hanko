"""A fixture stand-in for one RYO tool, shaped like RyoToolSource / RyoMcpSource.

`hanko.sources.fixture.FixtureSource` returns evidence items (posts, with an
author and a body). A RYO tool doesn't return evidence, it returns one raw
payload of facts -- so a fixture standing in for one needs a different
shape, and this is that shape rather than a variant of the other one.

Fixture file:

    {"status": "ok", "coverage": "complete", "payload": {"price_usd": 1.25}}
    {"status": "failed", "coverage": "unknown", "error": "rate limited"}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..provenance import Coverage, Status
from ..sources.base import Query, RawResponse


class FixtureFactsSource:
    adapter_version = "1.0.0"

    def __init__(self, path: str | Path, source_id: str) -> None:
        self.path = Path(path)
        self.source_id = source_id

    def fetch(self, query: Query) -> RawResponse:
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        status = Status(doc.get("status", "ok"))
        return RawResponse(
            payload=doc.get("payload") if status is not Status.FAILED else None,
            status=status,
            coverage=Coverage(doc.get("coverage", "unknown")),
            error=doc.get("error"),
            meta={"fixture": self.path.name},
        )

    def parse(self, payload: Any) -> list[dict[str, Any]]:
        """No evidence items -- a tool response is facts, not utterances."""
        return []
