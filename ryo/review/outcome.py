"""Grading a decision against what it committed to in advance.

The rule this module exists to enforce: a decision is graded against its own
pre-registered falsifiers, not against whether it happened to make money.

Those come apart more often than is comfortable. An entry can be profitable
and still falsified -- the price rose while the liquidity that justified the
size drained away, meaning the reasoning was wrong and the outcome was luck.
Both facts are recorded, kept separate, and reported separately. Grading on
profit alone is how an agent learns to repeat lucky mistakes.

The third outcome matters as much as the other two. When the metric a
falsifier names is unavailable at review time, the check is UNCHECKABLE. It
is never quietly counted as passing. A decision that could not be checked is
not a decision that was right, and an agent whose scorecard silently absorbs
its unverifiable calls is flattering itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..decision.record import DecisionRecord, Falsifier, MarketFacts, Outcome, Verdict
from ..provenance import digest, from_iso, to_iso


class CheckOutcome(str, Enum):
    MET = "met"  # the condition fired: this axis says the decision was wrong
    NOT_MET = "not_met"
    UNCHECKABLE = "uncheckable"  # the metric was not available at review time


class ReviewResult(str, Enum):
    HELD = "held"
    FALSIFIED = "falsified"
    # Nothing could be checked. Reported, and excluded from scoring, rather
    # than rounded to whichever answer looks better.
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class Observations:
    """Metric values at review time, with missing values kept as None."""

    at: datetime
    metrics: dict[str, float | None]
    snapshot_id: str | None = None

    @classmethod
    def from_market(
        cls,
        market: MarketFacts,
        at: datetime,
        *,
        independent_voices: int | None = None,
    ) -> "Observations":
        return cls(
            at=at,
            metrics={
                "price_usd": market.price_usd,
                "volume_24h_usd": market.volume_24h_usd,
                "liquidity_usd": market.liquidity_usd,
                "safety_score": market.safety_score,
                "independent_voices": (
                    float(independent_voices) if independent_voices is not None else None
                ),
            },
            snapshot_id=market.snapshot_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": to_iso(self.at),
            "metrics": self.metrics,
            "snapshot_id": self.snapshot_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Observations":
        return cls(
            at=from_iso(d["at"]),
            metrics=d["metrics"],
            snapshot_id=d.get("snapshot_id"),
        )


@dataclass(frozen=True, slots=True)
class FalsifierCheck:
    falsifier: Falsifier
    outcome: CheckOutcome
    observed: float | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "falsifier": self.falsifier.to_dict(),
            "outcome": self.outcome.value,
            "observed": self.observed,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FalsifierCheck":
        return cls(
            falsifier=Falsifier.from_dict(d["falsifier"]),
            outcome=CheckOutcome(d["outcome"]),
            observed=d.get("observed"),
            detail=d["detail"],
        )


@dataclass(frozen=True, slots=True)
class Review:
    decision_id: str
    subject: str
    verdict: Verdict
    confidence: float
    reviewed_at: datetime
    due_at: datetime
    early: bool  # reviewed before the pre-registered date
    result: ReviewResult
    checks: tuple[FalsifierCheck, ...]
    observations: Observations

    # Recorded, reported, and deliberately not used to decide `result`.
    realised_return: float | None

    # Who and what the decision leaned on, so credit and blame can be
    # attributed without re-reading the original reasoning.
    credited_authors: tuple[str, ...]
    credited_rules: tuple[str, ...]

    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def review_id(self) -> str:
        return "rev_" + digest(
            {
                "decision_id": self.decision_id,
                "reviewed_at": to_iso(self.reviewed_at),
                "result": self.result.value,
                "checks": [c.to_dict() for c in self.checks],
                "observations": self.observations.to_dict(),
            }
        ).removeprefix("sha256:")[:24]

    @property
    def scoreable(self) -> bool:
        return self.result is not ReviewResult.INCONCLUSIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "decision_id": self.decision_id,
            "subject": self.subject,
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "reviewed_at": to_iso(self.reviewed_at),
            "due_at": to_iso(self.due_at),
            "early": self.early,
            "result": self.result.value,
            "checks": [c.to_dict() for c in self.checks],
            "observations": self.observations.to_dict(),
            "realised_return": self.realised_return,
            "credited_authors": list(self.credited_authors),
            "credited_rules": list(self.credited_rules),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Review":
        return cls(
            decision_id=d["decision_id"],
            subject=d["subject"],
            verdict=Verdict(d["verdict"]),
            confidence=d["confidence"],
            reviewed_at=from_iso(d["reviewed_at"]),
            due_at=from_iso(d["due_at"]),
            early=d["early"],
            result=ReviewResult(d["result"]),
            checks=tuple(FalsifierCheck.from_dict(c) for c in d["checks"]),
            observations=Observations.from_dict(d["observations"]),
            realised_return=d.get("realised_return"),
            credited_authors=tuple(d.get("credited_authors", ())),
            credited_rules=tuple(d.get("credited_rules", ())),
            notes=d.get("notes", {}),
        )

    def explain(self) -> str:
        lines = [
            self.result.value.upper()
            + "  "
            + self.subject
            + "  ("
            + self.verdict.value
            + " at confidence "
            + str(round(self.confidence, 2))
            + ")",
            "  " + self.decision_id + " -> " + self.review_id,
        ]
        if self.early:
            lines.append("  reviewed early, before " + to_iso(self.due_at))
        for check in self.checks:
            mark = {
                CheckOutcome.MET: "  x ",
                CheckOutcome.NOT_MET: "  + ",
                CheckOutcome.UNCHECKABLE: "  ? ",
            }[check.outcome]
            lines.append(mark + check.detail)
        if self.realised_return is not None:
            lines.append(
                "  realised return "
                + str(round(self.realised_return * 100, 2))
                + "%  (recorded, not used to grade)"
            )
        return "\n".join(lines)


def review_decision(
    record: DecisionRecord,
    observations: Observations,
    *,
    reviewed_at: datetime | None = None,
) -> Review:
    """Grade one decision. Pure: a function of the record and the observations."""
    reviewed_at = reviewed_at or observations.at

    checks: list[FalsifierCheck] = []
    for falsifier in record.falsifiers:
        observed = observations.metrics.get(falsifier.metric)
        if observed is None:
            checks.append(
                FalsifierCheck(
                    falsifier=falsifier,
                    outcome=CheckOutcome.UNCHECKABLE,
                    observed=None,
                    detail=(
                        falsifier.metric
                        + " was not available at review time; this axis is"
                        " unresolved, not passed"
                    ),
                )
            )
            continue

        met = falsifier.is_met(observed)
        checks.append(
            FalsifierCheck(
                falsifier=falsifier,
                outcome=CheckOutcome.MET if met else CheckOutcome.NOT_MET,
                observed=observed,
                detail=(
                    falsifier.metric
                    + " observed at "
                    + str(observed)
                    + ("; committed to being wrong if " if met else "; holds against ")
                    + falsifier.comparator
                    + " "
                    + str(falsifier.threshold)
                    + (" -- " + falsifier.note if met else "")
                ),
            )
        )

    if any(c.outcome is CheckOutcome.MET for c in checks):
        result = ReviewResult.FALSIFIED
    elif any(c.outcome is CheckOutcome.NOT_MET for c in checks):
        result = ReviewResult.HELD
    else:
        result = ReviewResult.INCONCLUSIVE

    entry_price = record.market.price_usd
    exit_price = observations.metrics.get("price_usd")
    realised = None
    if (
        record.verdict is Verdict.ENTER
        and entry_price
        and exit_price is not None
    ):
        realised = round((exit_price - entry_price) / entry_price, 8)

    return Review(
        decision_id=record.decision_id,
        subject=record.subject,
        verdict=record.verdict,
        confidence=record.confidence,
        reviewed_at=reviewed_at,
        due_at=record.review_at,
        early=reviewed_at < record.review_at,
        result=result,
        checks=tuple(checks),
        observations=observations,
        realised_return=realised,
        credited_authors=record.convergence.independent_authors,
        credited_rules=tuple(
            sorted(r.rule_id for r in record.rules if r.outcome is Outcome.SATISFIED)
        ),
    )
