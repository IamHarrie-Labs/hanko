"""The Decision Record: a verdict that cannot be quietly rewritten.

A record states, at the moment of the decision:

    what was concluded          verdict, size, confidence
    on what evidence            cited evidence ids, back to snapshot bytes
    by what reasoning           the rules that fired, and what each one saw
    what was missing            gaps, named rather than glossed
    what would prove it wrong   falsifiers, and the date they are checked

The last line is the point. Hindsight rationalisation is the standard
failure of an LLM trading agent: ask it after a loss and it will explain
why the loss was foreseeable. Committing in advance to the conditions that
would falsify the thesis, and hashing that commitment into the identity of
the record itself, makes that impossible. Change a falsifier, a horizon, a
size, or the review date, and you have a different decision_id -- a new
decision, not an edited one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..provenance import digest, from_iso, to_iso
from .convergence import ConvergenceReport, Echo
from .policy import Policy
from .quality import EvidenceQuality, Gap
from .reading import Reading


class Verdict(str, Enum):
    ENTER = "enter"
    PASS = "pass"  # evidence was adequate and argued against the trade
    # Evidence was not adequate to argue either way. Kept distinct from
    # PASS on purpose: "I looked and decided no" and "I could not see"
    # are different claims, and only one of them is a market view.
    ABSTAIN = "abstain"


class Outcome(str, Enum):
    """How a rule resolved. Recorded for every rule, including the quiet ones."""

    SATISFIED = "satisfied"
    BLOCKED = "blocked"
    NOTED = "noted"


@dataclass(frozen=True, slots=True)
class RuleFiring:
    rule_id: str
    outcome: Outcome
    detail: str
    cites: tuple[str, ...] = ()  # evidence ids this conclusion rests on

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "outcome": self.outcome.value,
            "detail": self.detail,
            "cites": list(self.cites),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RuleFiring":
        return cls(
            rule_id=d["rule_id"],
            outcome=Outcome(d["outcome"]),
            detail=d["detail"],
            cites=tuple(d.get("cites", ())),
        )


@dataclass(frozen=True, slots=True)
class Falsifier:
    """A condition that, if met, means this decision was wrong.

    Written before the outcome is known and checked mechanically at
    review time. No prose, no room to reinterpret.
    """

    metric: str  # e.g. "price_usd", "liquidity_usd", "independent_voices"
    comparator: str  # "<" or ">"
    threshold: float
    horizon_hours: float
    note: str
    raised_by: str  # rule_id that committed to it

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "comparator": self.comparator,
            "threshold": self.threshold,
            "horizon_hours": self.horizon_hours,
            "note": self.note,
            "raised_by": self.raised_by,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Falsifier":
        return cls(
            metric=d["metric"],
            comparator=d["comparator"],
            threshold=float(d["threshold"]),
            horizon_hours=float(d["horizon_hours"]),
            note=d["note"],
            raised_by=d["raised_by"],
        )

    def is_met(self, observed: float) -> bool:
        return observed < self.threshold if self.comparator == "<" else observed > self.threshold


@dataclass(frozen=True, slots=True)
class MarketFacts:
    """Facts drawn from the RYO research tools.

    Every field is optional, and a None is carried through as a gap rather
    than defaulted. A zero here would be a fabricated number, which is the
    one thing the platform's honesty convention forbids outright.
    """

    subject: str
    price_usd: float | None = None
    volume_24h_usd: float | None = None
    liquidity_usd: float | None = None
    safety_score: float | None = None  # 0..1
    snapshot_id: str | None = None

    REQUIRED = ("price_usd", "volume_24h_usd", "liquidity_usd", "safety_score")

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(f for f in self.REQUIRED if getattr(self, f) is None)

    @property
    def present_count(self) -> int:
        return len(self.REQUIRED) - len(self.missing)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "price_usd": self.price_usd,
            "volume_24h_usd": self.volume_24h_usd,
            "liquidity_usd": self.liquidity_usd,
            "safety_score": self.safety_score,
            "snapshot_id": self.snapshot_id,
            "missing": list(self.missing),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MarketFacts":
        return cls(
            subject=d["subject"],
            price_usd=d.get("price_usd"),
            volume_24h_usd=d.get("volume_24h_usd"),
            liquidity_usd=d.get("liquidity_usd"),
            safety_score=d.get("safety_score"),
            snapshot_id=d.get("snapshot_id"),
        )


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    subject: str
    decided_at: datetime
    review_at: datetime
    verdict: Verdict
    size_fraction: float
    confidence: float

    quality: EvidenceQuality
    convergence: ConvergenceReport
    market: MarketFacts
    gaps: tuple[Gap, ...]
    rules: tuple[RuleFiring, ...]
    falsifiers: tuple[Falsifier, ...]

    readings: tuple[Reading, ...]
    snapshot_ids: tuple[str, ...]
    policy: Policy
    interpreter_id: str
    interpreter_version: str
    engine_version: str

    notes: dict[str, Any] = field(default_factory=dict)

    # ---- identity ------------------------------------------------------

    @property
    def commitment(self) -> dict[str, Any]:
        """The pre-registered part: everything claimed before the outcome.

        Deliberately excludes prose and diagnostics. What it covers is what
        the agent is held to.
        """
        return {
            "subject": self.subject,
            "decided_at": to_iso(self.decided_at),
            "review_at": to_iso(self.review_at),
            "verdict": self.verdict.value,
            "size_fraction": round(self.size_fraction, 8),
            "confidence": round(self.confidence, 8),
            "falsifiers": [f.to_dict() for f in self.falsifiers],
            "cited_evidence": sorted({r.evidence_id for r in self.readings}),
            "snapshot_ids": sorted(self.snapshot_ids),
            "policy_digest": self.policy.policy_digest,
            "interpreter": self.interpreter_id + "@" + self.interpreter_version,
            "engine_version": self.engine_version,
        }

    @property
    def commitment_digest(self) -> str:
        return digest(self.commitment)

    @property
    def decision_id(self) -> str:
        return "dec_" + self.commitment_digest.removeprefix("sha256:")[:24]

    # ---- serialisation --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "commitment_digest": self.commitment_digest,
            "commitment": self.commitment,
            "quality": self.quality.to_dict(),
            "convergence": self.convergence.to_dict(),
            "market": self.market.to_dict(),
            "gaps": [g.to_dict() for g in self.gaps],
            "rules": [r.to_dict() for r in self.rules],
            "readings": [r.to_dict() for r in self.readings],
            "policy": self.policy.to_dict(),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DecisionRecord":
        c = d["commitment"]
        conv = d["convergence"]
        interpreter_id, _, interpreter_version = c["interpreter"].partition("@")
        return cls(
            subject=c["subject"],
            decided_at=from_iso(c["decided_at"]),
            review_at=from_iso(c["review_at"]),
            verdict=Verdict(c["verdict"]),
            size_fraction=c["size_fraction"],
            confidence=c["confidence"],
            quality=EvidenceQuality.from_dict(d["quality"]),
            convergence=ConvergenceReport(
                subject=conv["subject"],
                mentions=conv["mentions"],
                distinct_authors=conv["distinct_authors"],
                independent_voices=conv["independent_voices"],
                independent_authors=tuple(conv["independent_authors"]),
                echoes=tuple(
                    Echo(
                        evidence_id=e["evidence_id"],
                        author=e["author"],
                        echoes=e["echoes"],
                        reason=e["reason"],
                    )
                    for e in conv["echoes"]
                ),
            ),
            market=MarketFacts.from_dict(d["market"]),
            gaps=tuple(Gap.from_dict(g) for g in d["gaps"]),
            rules=tuple(RuleFiring.from_dict(r) for r in d["rules"]),
            falsifiers=tuple(Falsifier.from_dict(f) for f in c["falsifiers"]),
            readings=tuple(Reading.from_dict(r) for r in d["readings"]),
            snapshot_ids=tuple(c["snapshot_ids"]),
            policy=Policy.from_dict(d["policy"]),
            interpreter_id=interpreter_id,
            interpreter_version=interpreter_version,
            engine_version=c["engine_version"],
            notes=d.get("notes", {}),
        )

    # ---- presentation ---------------------------------------------------

    def explain(self) -> str:
        """The reasoning trail as a human reads it. Derived, never stored."""
        lines = [
            self.verdict.value.upper()
            + " "
            + self.subject
            + "  size "
            + str(round(self.size_fraction * 100, 2))
            + "%  confidence "
            + str(round(self.confidence, 2)),
            "  " + self.decision_id,
            "  evidence quality " + str(round(self.quality.overall, 3))
            + "  (completeness " + str(round(self.quality.completeness, 2))
            + ", freshness " + str(round(self.quality.freshness, 2))
            + ", corroboration " + str(round(self.quality.corroboration, 2))
            + ", independence " + str(round(self.quality.independence, 2)) + ")",
        ]
        for rule in self.rules:
            mark = {
                Outcome.SATISFIED: "  + ",
                Outcome.BLOCKED: "  x ",
                Outcome.NOTED: "  . ",
            }[rule.outcome]
            lines.append(mark + rule.rule_id + ": " + rule.detail)
        for gap in self.gaps:
            lines.append("  ? gap " + gap.kind.value + ": " + gap.detail)
        for echo in self.convergence.echoes:
            lines.append("  ~ echo " + echo.author + ": " + echo.reason)
        for f in self.falsifiers:
            lines.append(
                "  ! wrong if " + f.metric + " " + f.comparator + " "
                + str(f.threshold) + " within " + str(f.horizon_hours) + "h"
                + " (" + f.note + ")"
            )
        lines.append("  review at " + to_iso(self.review_at))
        return "\n".join(lines)
