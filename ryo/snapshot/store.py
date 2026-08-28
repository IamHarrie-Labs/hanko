"""Append-only, content-addressed snapshot store.

Layout under the store root:

    objects/<aa>/<sha256>.json   payload bytes, deduplicated by content
    index.jsonl                  append-only envelope log, one JSON per line

Two properties this buys, both of which the reasoning trail depends on:

  Integrity  -- a payload is addressed by the hash of its own bytes, so a
                snapshot that has been altered cannot be loaded silently.
  Replay     -- an envelope plus a pure parse() reproduces the exact
                evidence a past decision saw, without touching the network.

Failures are stored, never dropped. A snapshot with status FAILED and no
payload is a record that the source was asked and did not answer. The
agent needs that fact to size a position honestly.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from ..evidence import Evidence
from ..provenance import (
    Coverage,
    Status,
    canonical_json,
    digest,
    digest_bytes,
    from_iso,
    to_iso,
    utcnow,
)
from ..sources.base import Query, RawResponse, Source, bind_provenance


class IntegrityError(RuntimeError):
    """Stored bytes do not match the address they were filed under."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One recorded interaction with one source."""

    snapshot_id: str
    sequence: int  # position in this store's append-only log
    source_id: str
    adapter_version: str
    query: dict[str, Any]
    requested_at: datetime
    received_at: datetime
    status: Status
    coverage: Coverage
    payload_digest: str | None
    error: str | None
    meta: dict[str, Any]

    @property
    def has_payload(self) -> bool:
        return self.payload_digest is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "sequence": self.sequence,
            "source_id": self.source_id,
            "adapter_version": self.adapter_version,
            "query": self.query,
            "requested_at": to_iso(self.requested_at),
            "received_at": to_iso(self.received_at),
            "status": self.status.value,
            "coverage": self.coverage.value,
            "payload_digest": self.payload_digest,
            "error": self.error,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Snapshot":
        return cls(
            snapshot_id=d["snapshot_id"],
            sequence=d["sequence"],
            source_id=d["source_id"],
            adapter_version=d["adapter_version"],
            query=d["query"],
            requested_at=from_iso(d["requested_at"]),
            received_at=from_iso(d["received_at"]),
            status=Status(d["status"]),
            coverage=Coverage(d["coverage"]),
            payload_digest=d.get("payload_digest"),
            error=d.get("error"),
            meta=d.get("meta", {}),
        )


def _snapshot_id(
    source_id: str,
    adapter_version: str,
    query: dict[str, Any],
    requested_at: datetime,
    payload_digest: str | None,
    sequence: int,
) -> str:
    """Identity of one observation event.

    The payload is content-addressed separately; this identifies the act of
    observing it. The sequence number is load-bearing: the system clock is
    coarse enough on some platforms that two consecutive collections share
    a timestamp, and two observations must not collapse into one record
    just because the clock could not tell them apart.
    """
    return "snap_" + digest(
        {
            "source_id": source_id,
            "adapter_version": adapter_version,
            "query": query,
            "requested_at": to_iso(requested_at),
            "payload_digest": payload_digest,
            "sequence": sequence,
        }
    ).removeprefix("sha256:")[:24]


class SnapshotStore:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.index_path = self.root / "index.jsonl"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.index_path.touch(exist_ok=True)
        with self.index_path.open("r", encoding="utf-8") as fh:
            self._sequence = sum(1 for line in fh if line.strip())

    # ---- writing -------------------------------------------------------

    def _object_path(self, payload_digest: str) -> Path:
        hex_part = payload_digest.removeprefix("sha256:")
        return self.objects / hex_part[:2] / (hex_part + ".json")

    def _write_payload(self, payload: Any) -> str:
        raw = canonical_json(payload)
        addr = digest_bytes(raw)
        path = self._object_path(addr)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write then rename, so a crash cannot leave a half-written
            # object sitting at a valid content address.
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(raw)
            tmp.replace(path)
        return addr

    def put(
        self,
        *,
        source_id: str,
        adapter_version: str,
        query: Query,
        response: RawResponse,
        requested_at: datetime,
        received_at: datetime | None = None,
    ) -> Snapshot:
        received_at = received_at or utcnow()
        payload_digest = (
            self._write_payload(response.payload)
            if response.status is not Status.FAILED
            else None
        )
        query_dict = query.to_dict()
        sequence = self._sequence
        snap = Snapshot(
            snapshot_id=_snapshot_id(
                source_id,
                adapter_version,
                query_dict,
                requested_at,
                payload_digest,
                sequence,
            ),
            sequence=sequence,
            source_id=source_id,
            adapter_version=adapter_version,
            query=query_dict,
            requested_at=requested_at,
            received_at=received_at,
            status=response.status,
            coverage=response.coverage,
            payload_digest=payload_digest,
            error=response.error,
            meta=response.meta,
        )
        with self.index_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snap.to_dict(), ensure_ascii=False) + "\n")
        return snap

    def collect(self, source: Source, query: Query) -> Snapshot:
        """Fetch and record, turning a raised exception into a FAILED snapshot.

        An adapter that throws still produces a record. Silence is the one
        outcome this store will not represent.
        """
        requested_at = utcnow()
        try:
            response = source.fetch(query)
        except Exception as exc:  # noqa: BLE001 - the failure is itself data
            response = RawResponse(
                payload=None,
                status=Status.FAILED,
                coverage=Coverage.UNKNOWN,
                error=type(exc).__name__ + ": " + str(exc),
            )
        return self.put(
            source_id=source.source_id,
            adapter_version=source.adapter_version,
            query=query,
            response=response,
            requested_at=requested_at,
        )

    # ---- reading -------------------------------------------------------

    def load_payload(self, payload_digest: str) -> Any:
        path = self._object_path(payload_digest)
        if not path.exists():
            raise FileNotFoundError("no object for " + payload_digest)
        raw = path.read_bytes()
        actual = digest_bytes(raw)
        if actual != payload_digest:
            raise IntegrityError(
                "object at " + str(path) + " hashes to " + actual
                + ", filed as " + payload_digest
            )
        return json.loads(raw)

    def __iter__(self) -> Iterator[Snapshot]:
        with self.index_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield Snapshot.from_dict(json.loads(line))

    def get(self, snapshot_id: str) -> Snapshot:
        for snap in self:
            if snap.snapshot_id == snapshot_id:
                return snap
        raise KeyError(snapshot_id)

    def find(
        self,
        *,
        source_id: str | None = None,
        status: Status | None = None,
        since: datetime | None = None,
    ) -> list[Snapshot]:
        out: list[Snapshot] = []
        for snap in self:
            if source_id and snap.source_id != source_id:
                continue
            if status and snap.status is not status:
                continue
            if since and snap.requested_at < since:
                continue
            out.append(snap)
        return out

    # ---- replay --------------------------------------------------------

    def replay(self, snapshot_id: str, source: Source) -> list[Evidence]:
        """Re-derive the evidence a snapshot produced, from stored bytes only.

        No network. Given the same store and the same adapter version, this
        returns identical evidence every time it is called.
        """
        snap = self.get(snapshot_id)
        if snap.adapter_version != source.adapter_version:
            raise ValueError(
                snapshot_id + " was captured by " + snap.source_id + "@"
                + snap.adapter_version + ", replaying with " + source.adapter_version
            )
        if not snap.has_payload:
            return []
        assert snap.payload_digest is not None
        payload = self.load_payload(snap.payload_digest)
        items = source.parse(payload)
        return bind_provenance(
            items,
            snapshot_id=snap.snapshot_id,
            payload_digest=snap.payload_digest,
            source_id=snap.source_id,
            adapter_version=snap.adapter_version,
        )

    def verify(self) -> list[str]:
        """Check every referenced object is present and hashes correctly.

        Returns human-readable problems; empty means the store is
        internally consistent. Wired into CI.
        """
        problems: list[str] = []
        for snap in self:
            if not snap.has_payload:
                continue
            assert snap.payload_digest is not None
            try:
                self.load_payload(snap.payload_digest)
            except (FileNotFoundError, IntegrityError) as exc:
                problems.append(snap.snapshot_id + ": " + str(exc))
        return problems
