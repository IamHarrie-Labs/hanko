"""Anchor a manifest digest to public OpenTimestamps calendars.

A tweet gets a run's `manifest_digest` seen, by people, at roughly the time
it was posted. It proves nothing on its own -- X's timestamps are not an
independently verifiable record. OpenTimestamps is: a calendar server
returns a proof that a digest was submitted before a given moment, and that
proof is later confirmed by a Bitcoin block that already existed before
this code ran. The proof is `pending` until a block actually includes it,
usually within a few hours; a proof that has not yet upgraded must stay
labelled `pending`, not treated as confirmed.

This module talks to `opentimestamps.calendar` directly rather than
shelling out to the `ots` CLI. The CLI (`opentimestamps-client`) imports
`python-bitcoinlib`'s RPC module unconditionally, which tries to load
OpenSSL via `ctypes.cdll.LoadLibrary` at import time -- a call that fails
on a stock Windows Python install with no system OpenSSL on `PATH`, even
for calendar-only stamping that never touches a node. The calendar
submission path itself carries no such dependency.

Only the calendar digest is stamped, never the file's raw bytes -- the
digest already equals `manifest_digest` (sha256 of the manifest's own
canonical JSON), so what gets anchored is exactly the number that gets
posted and printed, not an artifact of `json.dumps`'s particular
whitespace.
"""

from __future__ import annotations

from pathlib import Path

from opentimestamps.calendar import RemoteCalendar
from opentimestamps.core.op import OpSHA256
from opentimestamps.core.serialize import BytesDeserializationContext, BytesSerializationContext
from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

# The standard public OTS calendar set (the same three `ots stamp` submits
# to by default). Redundant on purpose: one calendar going dark does not
# lose the timestamp, since a proof merges attestations from every
# calendar that answered.
DEFAULT_CALENDARS = (
    "https://alice.btc.calendar.opentimestamps.org",
    "https://bob.btc.calendar.opentimestamps.org",
    "https://finney.calendar.eternitywall.com",
)


class StampFailed(RuntimeError):
    """Every configured calendar refused or timed out."""


def stamp_digest(
    digest_hex: str,
    *,
    calendars: tuple[str, ...] = DEFAULT_CALENDARS,
    timeout: float = 15.0,
) -> bytes:
    """Submit a bare sha256 digest (hex, no `sha256:` prefix) to the calendars.

    Returns serialized `.ots` proof bytes. Raises only if every calendar
    fails; a partial success (2 of 3 calendars, say) still returns a valid,
    merged proof, because that is OpenTimestamps' own redundancy model.
    """
    msg = bytes.fromhex(digest_hex)
    merged = Timestamp(msg)
    errors: list[str] = []
    successes = 0
    for url in calendars:
        try:
            cal = RemoteCalendar(url)
            merged.merge(cal.submit(msg, timeout=timeout))
            successes += 1
        except Exception as exc:  # noqa: BLE001 -- one calendar's failure is not fatal
            errors.append(url + ": " + type(exc).__name__ + ": " + str(exc))
    if successes == 0:
        raise StampFailed("every calendar failed: " + "; ".join(errors))

    detached = DetachedTimestampFile(OpSHA256(), merged)
    ctx = BytesSerializationContext()
    detached.serialize(ctx)
    return ctx.getbytes()


def load_proof(path: str | Path) -> DetachedTimestampFile:
    ctx = BytesDeserializationContext(Path(path).read_bytes())
    return DetachedTimestampFile.deserialize(ctx)


def is_confirmed(proof: DetachedTimestampFile) -> bool:
    """True once at least one attestation is a Bitcoin block, not just a calendar receipt.

    A freshly stamped proof is never confirmed yet -- a calendar server
    only hands back its receipt immediately; the Bitcoin attestation that
    actually anchors it is added later, once a block includes it.
    """
    from opentimestamps.core.notary import BitcoinBlockHeaderAttestation

    return any(
        isinstance(att, BitcoinBlockHeaderAttestation)
        for _, att in proof.timestamp.all_attestations()
    )


def stamp_and_save(digest_hex: str, out_path: str | Path, **kwargs) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(stamp_digest(digest_hex, **kwargs))
    return out_path
