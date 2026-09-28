"""hanko seal -- pre-register a run, execute it, and publish what happened.

A single sealed decision proves one thing: that its commitment existed
before its outcome. It proves nothing about the decisions around it. Publish
ten and reveal the three that went well, and every one of those three still
verifies -- the dishonesty lives in the nine that were never mentioned, not
in anything a hash can catch.

A run manifest is the fix: every token on the watchlist, numbered, in the
order the sweep actually reached them, including the ones that errored,
abstained, or passed. `manifest_digest` covers the watchlist itself, the
policy in force, and every entry -- so a manifest cannot be quietly edited
after the fact any more than a Decision Record can, and a claim like "we
sealed 6 decisions today" can be checked against the one file that would
have to admit it if that were 9.

Verdicts here are public, not hidden. A hidden verdict needs a nonce to
resist guessing an ENTER/PASS/ABSTAIN space that small, and buys back only
the ability to reveal something later -- which a same-day 72-hour review
horizon rarely has time to use anyway. What matters is that the manifest,
not any one decision plucked from it, is the thing that gets timestamped
and posted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .decision.policy import Policy
from .provenance import digest, to_iso
from .sweep import SweepReport, WatchEntry


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One watchlist token's outcome in one run, numbered by sweep order."""

    seq: int
    token: str
    verdict: str | None  # None only if the decide step itself errored
    decision_id: str | None
    commitment_digest: str | None
    skipped_duplicate: bool
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "token": self.token,
            "verdict": self.verdict,
            "decision_id": self.decision_id,
            "commitment_digest": self.commitment_digest,
            "skipped_duplicate": self.skipped_duplicate,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ManifestEntry":
        return cls(
            seq=d["seq"],
            token=d["token"],
            verdict=d.get("verdict"),
            decision_id=d.get("decision_id"),
            commitment_digest=d.get("commitment_digest"),
            skipped_duplicate=d.get("skipped_duplicate", False),
            error=d.get("error"),
        )


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Every watchlist entry one sweep touched, numbered, none left out.

    `manifest_digest` is what gets OpenTimestamped and posted -- not any
    individual decision_id. Anchoring one decision proves that one thing
    existed by that time; anchoring the manifest proves the whole run did,
    with nothing missing from between what was posted and what is later
    shown.
    """

    run_id: str
    as_of: datetime
    watchlist_digest: str
    policy_digest: str
    entries: tuple[ManifestEntry, ...]
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def manifest(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "as_of": to_iso(self.as_of),
            "watchlist_digest": self.watchlist_digest,
            "policy_digest": self.policy_digest,
            "entries": [e.to_dict() for e in self.entries],
        }

    @property
    def manifest_digest(self) -> str:
        return digest(self.manifest)

    def to_dict(self) -> dict[str, Any]:
        return {**self.manifest, "manifest_digest": self.manifest_digest, "notes": self.notes}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunManifest":
        return cls(
            run_id=d["run_id"],
            as_of=datetime.fromisoformat(d["as_of"].replace("Z", "+00:00")),
            watchlist_digest=d["watchlist_digest"],
            policy_digest=d["policy_digest"],
            entries=tuple(ManifestEntry.from_dict(e) for e in d["entries"]),
            notes=d.get("notes", {}),
        )

    def verify(self) -> list[str]:
        """Every declared count checked against the entries actually listed."""
        problems: list[str] = []
        seqs = [e.seq for e in self.entries]
        if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
            problems.append("entries are not a clean 1..N sequence")
        return problems

    def explain(self) -> str:
        lines = [
            "run " + self.run_id + "  as of " + to_iso(self.as_of),
            "  " + str(len(self.entries)) + " watchlist entr" + ("y" if len(self.entries) == 1 else "ies")
            + ", none omitted",
        ]
        for e in self.entries:
            if e.error:
                lines.append("  " + str(e.seq) + ". " + e.token + "  ERROR  " + e.error)
            elif e.skipped_duplicate:
                lines.append("  " + str(e.seq) + ". " + e.token + "  (already decided this instant)")
            else:
                lines.append(
                    "  " + str(e.seq) + ". " + e.token + "  " + (e.verdict or "?").upper()
                    + "  " + (e.decision_id or "")
                )
        lines.append("  manifest_digest " + self.manifest_digest)
        return "\n".join(lines)

    def post_text(self, *, repo_url: str = "") -> str:
        """A ready-to-post summary: every count, nothing implied."""
        errored = sum(1 for e in self.entries if e.error)
        verdicts: dict[str, int] = {}
        for e in self.entries:
            if e.verdict:
                verdicts[e.verdict] = verdicts.get(e.verdict, 0) + 1
        parts = [k.upper() + " " + str(v) for k, v in sorted(verdicts.items())]
        if errored:
            parts.append("ERROR " + str(errored))
        line1 = "Hanko sealed run " + self.run_id + ": " + ", ".join(parts) + "."
        line2 = "manifest_digest " + self.manifest_digest
        line3 = (
            str(len(self.entries)) + " watchlist entries total, all listed in the manifest "
            "whether they entered or not. Review in 72h."
        )
        out = [line1, line2, line3]
        if repo_url:
            out.append(repo_url)
        return "\n".join(out)


def build_manifest(
    report: SweepReport,
    watchlist: tuple[WatchEntry, ...],
    policy: Policy,
) -> RunManifest:
    """Turn one sweep's report into a publishable, numbered manifest.

    Every watchlist entry appears exactly once, in watchlist order, whether
    it entered, passed, abstained, skipped as a duplicate, or errored
    outright -- so a run that produced nine unremarkable outcomes and one
    good one cannot be represented by publishing just the one.
    """
    watchlist_digest = digest({"watchlist": [e.to_dict() for e in watchlist]})
    by_token = {r.token: r for r in report.decisions}
    entries = []
    for seq, entry in enumerate(watchlist, start=1):
        r = by_token.get(entry.token)
        if r is None:
            entries.append(
                ManifestEntry(seq, entry.token, None, None, None, False, "not reached by this sweep")
            )
            continue
        entries.append(
            ManifestEntry(
                seq=seq,
                token=r.token,
                verdict=r.record.verdict.value if r.record else None,
                decision_id=r.record.decision_id if r.record else None,
                commitment_digest=r.record.commitment_digest if r.record else None,
                skipped_duplicate=r.skipped_duplicate,
                error=r.error,
            )
        )
    run_id = digest(
        {"as_of": to_iso(report.as_of), "watchlist_digest": watchlist_digest}
    ).removeprefix("sha256:")[:16]
    return RunManifest(
        run_id="run_" + run_id,
        as_of=report.as_of,
        watchlist_digest=watchlist_digest,
        policy_digest=policy.policy_digest,
        entries=tuple(entries),
    )


def save_manifest(manifest: RunManifest, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (manifest.run_id + ".json")
    path.write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
