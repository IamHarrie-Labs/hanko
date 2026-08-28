"""The store's guarantees, stated as tests.

These are the properties every later claim about the reasoning trail rests
on. If one of these breaks, "repeatable reasoning trail" stops being true.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ryo.provenance import Coverage, Status, canonical_json, digest
from ryo.snapshot import IntegrityError, SnapshotStore
from ryo.sources import FixtureSource, Query, RawResponse

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture()
def store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "snapshots")


@pytest.fixture()
def x_source() -> FixtureSource:
    return FixtureSource(FIXTURES / "x_three_voices.json", source_id="x")


# ---- canonical form -----------------------------------------------------


def test_canonical_json_is_key_order_independent():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_digest_is_stable_across_equivalent_values():
    assert digest({"a": [1, {"z": None, "y": 2}]}) == digest({"a": [1, {"y": 2, "z": None}]})


def test_canonical_json_refuses_nan():
    # NaN has no JSON representation, so it cannot have a stable address.
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


# ---- capture ------------------------------------------------------------


def test_collect_stores_payload_and_returns_evidence(store, x_source):
    snap = store.collect(x_source, Query(subjects=("voice_alpha",)))
    assert snap.status is Status.OK
    assert snap.has_payload

    evidence = store.replay(snap.snapshot_id, x_source)
    assert [e.author for e in evidence] == ["voice_alpha", "voice_beta", "voice_gamma"]
    assert all(e.provenance.snapshot_id == snap.snapshot_id for e in evidence)


def test_identical_payloads_are_stored_once(store, x_source):
    q = Query(subjects=("voice_alpha",))
    a = store.collect(x_source, q)
    b = store.collect(x_source, q)
    assert a.payload_digest == b.payload_digest
    assert a.snapshot_id != b.snapshot_id  # different instants, same bytes
    objects = list((store.objects).rglob("*.json"))
    assert len(objects) == 1


# ---- honest failure -----------------------------------------------------


def test_failed_source_is_recorded_not_dropped(store):
    source = FixtureSource(FIXTURES / "x_rate_limited.json", source_id="x")
    snap = store.collect(source, Query(subjects=("voice_alpha",)))

    assert snap.status is Status.FAILED
    assert snap.payload_digest is None
    assert "rate limited" in (snap.error or "")
    # The record exists. Downstream can see the source was asked and
    # did not answer, which is what makes honest sizing possible.
    assert store.get(snap.snapshot_id).status is Status.FAILED
    assert store.replay(snap.snapshot_id, source) == []


def test_raising_adapter_becomes_a_failed_snapshot(store):
    class Exploding:
        source_id = "x"
        adapter_version = "1.0.0"

        def fetch(self, query):
            raise ConnectionResetError("upstream closed the connection")

        def parse(self, payload):
            return []

    snap = store.collect(Exploding(), Query(subjects=("voice_alpha",)))
    assert snap.status is Status.FAILED
    assert "ConnectionResetError" in (snap.error or "")


def test_degraded_coverage_survives_the_round_trip(store):
    source = FixtureSource(FIXTURES / "x_partial_window.json", source_id="x")
    snap = store.collect(source, Query(subjects=("voice_alpha",)))
    assert snap.status is Status.DEGRADED
    assert snap.coverage is Coverage.PARTIAL
    assert store.get(snap.snapshot_id).coverage is Coverage.PARTIAL


def test_empty_result_is_not_confused_with_failure(store):
    source = FixtureSource(FIXTURES / "x_empty.json", source_id="x")
    snap = store.collect(source, Query(subjects=("voice_alpha",)))
    # "nobody said anything" is an OK answer, and a different fact from
    # "the source did not answer".
    assert snap.status is Status.OK
    assert store.replay(snap.snapshot_id, source) == []


# ---- integrity ----------------------------------------------------------


def test_tampered_object_is_rejected(store, x_source):
    snap = store.collect(x_source, Query(subjects=("voice_alpha",)))
    path = store._object_path(snap.payload_digest)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["items"][0]["text"] = "Accumulating $TOKENA. 100x incoming."
    path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(IntegrityError):
        store.load_payload(snap.payload_digest)
    assert store.verify()  # verify() reports the problem rather than hiding it


def test_verify_passes_on_a_clean_store(store, x_source):
    store.collect(x_source, Query(subjects=("voice_alpha",)))
    assert store.verify() == []


def test_replay_refuses_a_mismatched_adapter_version(store, x_source):
    snap = store.collect(x_source, Query(subjects=("voice_alpha",)))

    newer = FixtureSource(FIXTURES / "x_three_voices.json", source_id="x")
    newer.adapter_version = "2.0.0"
    with pytest.raises(ValueError, match="replaying with"):
        store.replay(snap.snapshot_id, newer)


# ---- the core promise ---------------------------------------------------


def test_replay_is_deterministic(store, x_source):
    snap = store.collect(x_source, Query(subjects=("voice_alpha",)))
    first = [e.to_dict() for e in store.replay(snap.snapshot_id, x_source)]
    for _ in range(5):
        again = [e.to_dict() for e in store.replay(snap.snapshot_id, x_source)]
        assert again == first


def test_evidence_id_is_pinned_to_bytes_and_position(store, x_source):
    snap = store.collect(x_source, Query(subjects=("voice_alpha",)))
    evidence = store.replay(snap.snapshot_id, x_source)
    ids = [e.evidence_id for e in evidence]

    assert len(set(ids)) == len(ids)
    # Same bytes, captured again at a different instant, still yields the
    # same evidence identities -- so a decision can cite evidence rather
    # than re-describe it.
    later = store.collect(x_source, Query(subjects=("voice_alpha",)))
    assert [e.evidence_id for e in store.replay(later.snapshot_id, x_source)] == ids


def test_store_survives_reopening(tmp_path, x_source):
    root = tmp_path / "snapshots"
    snap = SnapshotStore(root).collect(x_source, Query(subjects=("voice_alpha",)))
    reopened = SnapshotStore(root)
    assert reopened.get(snap.snapshot_id).payload_digest == snap.payload_digest
    assert len(reopened.replay(snap.snapshot_id, x_source)) == 3


def test_find_filters_by_source_and_status(store, x_source):
    store.collect(x_source, Query(subjects=("a",)))
    store.collect(
        FixtureSource(FIXTURES / "x_rate_limited.json", source_id="x"),
        Query(subjects=("b",)),
    )
    assert len(store.find(source_id="x")) == 2
    assert len(store.find(status=Status.FAILED)) == 1
    assert len(store.find(since=datetime(2030, 1, 1, tzinfo=timezone.utc))) == 0
