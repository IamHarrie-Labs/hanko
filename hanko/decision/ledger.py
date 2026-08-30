"""Append-only decision ledger, and the replay proof.

The ledger stores records. replay_decision() is the part that matters: it
rebuilds the inputs from stored snapshot bytes and recorded readings, runs
the engine again, and hands back a fresh record. If the two decision_ids
differ, something that was supposed to be deterministic was not.

Run over a corpus of stored decisions in CI, that turns "preserves a
repeatable reasoning trail" from a claim in a README into a failing build.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Iterator

from ..snapshot import SnapshotStore
from ..sources import Source, resolve
from .engine import DecisionInputs, decide
from .quality import Gap, GapKind
from .record import DecisionRecord, Verdict

_SOURCE_LEVEL_GAPS = {
    GapKind.SOURCE_FAILED,
    GapKind.COVERAGE_PARTIAL,
    GapKind.COVERAGE_UNKNOWN,
}


class DuplicateDecision(RuntimeError):
    """This exact decision is already on the ledger."""


class ReplayMismatch(AssertionError):
    """A stored decision did not reproduce from its own inputs."""


class DecisionLedger:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, record: DecisionRecord) -> DecisionRecord:
        if any(r.decision_id == record.decision_id for r in self):
            raise DuplicateDecision(record.decision_id)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def __iter__(self) -> Iterator[DecisionRecord]:
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield DecisionRecord.from_dict(json.loads(line))

    def get(self, decision_id: str) -> DecisionRecord:
        for record in self:
            if record.decision_id == decision_id:
                return record
        raise KeyError(decision_id)

    def find(
        self,
        *,
        subject: str | None = None,
        verdict: Verdict | None = None,
    ) -> list[DecisionRecord]:
        out = []
        for record in self:
            if subject and record.subject != subject.upper():
                continue
            if verdict and record.verdict is not verdict:
                continue
            out.append(record)
        return out

    def verify(self) -> list[str]:
        """Check each stored record still hashes to the id it is filed under.

        Editing a falsifier, a size, or a review date after the fact breaks
        this, which is the entire point of hashing the commitment.
        """
        problems: list[str] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for number, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                stored = json.loads(line)
                record = DecisionRecord.from_dict(stored)
                if record.decision_id != stored["decision_id"]:
                    problems.append(
                        "line " + str(number) + ": filed as "
                        + stored["decision_id"] + ", recomputes to "
                        + record.decision_id
                    )
                if record.commitment_digest != stored["commitment_digest"]:
                    problems.append(
                        "line " + str(number) + ": commitment digest does not match"
                    )
        return problems


def replay_decision(
    record: DecisionRecord,
    store: SnapshotStore,
    resolve_source: Callable[[str], Source] = resolve,
) -> DecisionRecord:
    """Re-run a stored decision from stored bytes. No network, no model.

    Evidence is re-derived from the snapshots the record cites. Readings are
    taken from the record rather than re-interpreted: interpretation is the
    subjective step, and it was frozen at decision time on purpose. What is
    being proven here is that the *reasoning* is reproducible.
    """
    evidence = []
    for snapshot_id in record.snapshot_ids:
        snap = store.get(snapshot_id)
        evidence.extend(store.replay(snapshot_id, resolve_source(snap.source_id)))

    cited = {r.evidence_id for r in record.readings}
    evidence = [e for e in evidence if e.evidence_id in cited]

    source_gaps = tuple(g for g in record.gaps if g.kind in _SOURCE_LEVEL_GAPS)

    inputs = DecisionInputs(
        subject=record.subject,
        evidence=tuple(evidence),
        readings=record.readings,
        market=record.market,
        as_of=record.decided_at,
        snapshot_ids=record.snapshot_ids,
        source_gaps=source_gaps,
        sources_requested=int(record.notes.get("sources_requested", 1)),
        interpreter_id=record.interpreter_id,
        interpreter_version=record.interpreter_version,
        notes=record.notes,
    )
    return decide(inputs, record.policy)


def assert_reproduces(
    record: DecisionRecord,
    store: SnapshotStore,
    resolve_source: Callable[[str], Source] = resolve,
) -> DecisionRecord:
    """Replay and insist on an identical decision id."""
    again = replay_decision(record, store, resolve_source)
    if again.decision_id == record.decision_id:
        return again

    differences = []
    original, replayed = record.commitment, again.commitment
    for key in sorted(set(original) | set(replayed)):
        if original.get(key) != replayed.get(key):
            differences.append(
                "  " + key + ": " + json.dumps(original.get(key))
                + " -> " + json.dumps(replayed.get(key))
            )
    raise ReplayMismatch(
        record.decision_id + " did not reproduce (" + again.decision_id + ")\n"
        + "\n".join(differences)
    )
