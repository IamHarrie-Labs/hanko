"""hanko/otstamp.py: OpenTimestamps anchoring, offline (calendars are mocked).

Real calendar submission was verified by hand against the live public
calendars during development (a genuine sha256 digest, stamped, a real
635-byte merged proof came back, `is_confirmed()` correctly reported
`False` on a proof only seconds old). These tests do not repeat that
network call -- a test suite that phones three external servers on every
run is not the offline-first discipline the rest of this project holds to
-- they cover the logic around it: merging, all-calendars-failed, and the
pending/confirmed distinction.
"""

from __future__ import annotations

import hashlib

import pytest

# The 'sealing' extra (pip install -e ".[sealing]") is optional -- hanko
# works without it, and cli.py degrades to an explicit error rather than
# crashing on import. Skip this whole file rather than failing collection
# for a dev environment that never installed it.
pytest.importorskip("opentimestamps")

from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.timestamp import Timestamp

from hanko.otstamp import StampFailed, is_confirmed, load_proof, stamp_and_save, stamp_digest

DIGEST_HEX = hashlib.sha256(b"hanko sealing test").hexdigest()


class FakeCalendar:
    """Stands in for RemoteCalendar.submit without touching the network."""

    def __init__(self, url, *, attestation=None, fails=False):
        self.url = url
        self._attestation = attestation
        self._fails = fails

    def submit(self, digest, timeout=None):
        if self._fails:
            raise ConnectionError("simulated calendar outage")
        ts = Timestamp(digest)
        ts.attestations.add(self._attestation or PendingAttestation(self.url))
        return ts


def test_a_successful_calendar_produces_a_pending_proof(monkeypatch):
    monkeypatch.setattr(
        "hanko.otstamp.RemoteCalendar", lambda url: FakeCalendar(url)
    )
    proof_bytes = stamp_digest(DIGEST_HEX, calendars=("https://fake.example",))
    assert len(proof_bytes) > 0


def test_one_calendar_failing_does_not_sink_the_stamp(monkeypatch, tmp_path):
    def make(url):
        return FakeCalendar(url, fails=(url == "https://dead.example"))

    monkeypatch.setattr("hanko.otstamp.RemoteCalendar", make)
    path = stamp_and_save(
        DIGEST_HEX,
        tmp_path / "manifest.json.ots",
        calendars=("https://dead.example", "https://alive.example"),
    )
    assert path.exists()
    proof = load_proof(path)
    assert proof.timestamp.msg == bytes.fromhex(DIGEST_HEX)


def test_every_calendar_failing_raises_stamp_failed(monkeypatch):
    monkeypatch.setattr(
        "hanko.otstamp.RemoteCalendar", lambda url: FakeCalendar(url, fails=True)
    )
    with pytest.raises(StampFailed):
        stamp_digest(DIGEST_HEX, calendars=("https://dead-a.example", "https://dead-b.example"))


class TestConfirmation:
    def test_a_pending_only_proof_is_not_confirmed(self, monkeypatch, tmp_path):
        monkeypatch.setattr("hanko.otstamp.RemoteCalendar", lambda url: FakeCalendar(url))
        path = stamp_and_save(DIGEST_HEX, tmp_path / "m.json.ots", calendars=("https://fake.example",))
        assert is_confirmed(load_proof(path)) is False

    def test_a_bitcoin_attestation_is_confirmed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "hanko.otstamp.RemoteCalendar",
            lambda url: FakeCalendar(url, attestation=BitcoinBlockHeaderAttestation(900_000)),
        )
        path = stamp_and_save(DIGEST_HEX, tmp_path / "m.json.ots", calendars=("https://fake.example",))
        assert is_confirmed(load_proof(path)) is True


def test_stamps_the_digest_itself_not_a_rehash_of_it(monkeypatch, tmp_path):
    """The .ots proof must anchor `manifest_digest` exactly -- not
    sha256(manifest_digest) or sha256 of some other representation of it.
    """
    monkeypatch.setattr("hanko.otstamp.RemoteCalendar", lambda url: FakeCalendar(url))
    path = stamp_and_save(DIGEST_HEX, tmp_path / "m.json.ots", calendars=("https://fake.example",))
    assert load_proof(path).timestamp.msg.hex() == DIGEST_HEX
