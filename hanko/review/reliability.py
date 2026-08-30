"""Turning a pile of reviews into a track record the agent can act on.

Three things come out of here.

  Calibration -- when this agent says 0.8, how often is it right? A Brier
  score plus the bucket table underneath it, so the number can be argued
  with rather than taken on faith.

  Per-author reliability -- of the voices this agent trusts, which ones
  precede decisions that hold? Earned from its own audited history, not
  asserted from follower counts. This is what a reputation score should
  mean, and it is the number that feeds back into weighting evidence.

  Per-rule reliability -- which of the agent's own rules were satisfied on
  decisions that later failed? A rule that is always satisfied on losers is
  not a filter, it is decoration.

Inconclusive reviews are excluded from every rate and reported separately.
An agent that quietly drops what it could not check is grading itself on a
sample it chose after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .outcome import Review, ReviewResult

_BUCKETS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001))


@dataclass(frozen=True, slots=True)
class Reliability:
    key: str
    held: int
    falsified: int
    inconclusive: int

    @property
    def scored(self) -> int:
        return self.held + self.falsified

    @property
    def hit_rate(self) -> float | None:
        """None rather than 0.0 when nothing has been scored yet.

        A voice with no scored decisions has no track record. Reporting it
        as 0% would defame it; reporting it as 100% would promote it.
        """
        return self.held / self.scored if self.scored else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "held": self.held,
            "falsified": self.falsified,
            "inconclusive": self.inconclusive,
            "scored": self.scored,
            "hit_rate": round(self.hit_rate, 6) if self.hit_rate is not None else None,
        }


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    low: float
    high: float
    count: int
    mean_confidence: float | None
    hit_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "range": [self.low, min(self.high, 1.0)],
            "count": self.count,
            "mean_confidence": (
                round(self.mean_confidence, 6) if self.mean_confidence is not None else None
            ),
            "hit_rate": round(self.hit_rate, 6) if self.hit_rate is not None else None,
        }


@dataclass(frozen=True, slots=True)
class Scorecard:
    reviewed: int
    scored: int
    inconclusive: int
    held: int
    falsified: int
    brier: float | None
    buckets: tuple[CalibrationBucket, ...]
    authors: tuple[Reliability, ...]
    rules: tuple[Reliability, ...]

    @property
    def hit_rate(self) -> float | None:
        return self.held / self.scored if self.scored else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reviewed": self.reviewed,
            "scored": self.scored,
            "inconclusive": self.inconclusive,
            "held": self.held,
            "falsified": self.falsified,
            "hit_rate": round(self.hit_rate, 6) if self.hit_rate is not None else None,
            "brier": round(self.brier, 6) if self.brier is not None else None,
            "calibration": [b.to_dict() for b in self.buckets],
            "authors": [a.to_dict() for a in self.authors],
            "rules": [r.to_dict() for r in self.rules],
        }

    def render(self) -> str:
        lines = [
            "reviewed " + str(self.reviewed)
            + "   scored " + str(self.scored)
            + "   unverifiable " + str(self.inconclusive),
        ]
        if self.scored:
            lines.append(
                "held " + str(self.held) + "   falsified " + str(self.falsified)
                + "   hit rate " + str(round((self.hit_rate or 0) * 100, 1)) + "%"
                + "   brier " + str(round(self.brier or 0, 4))
            )
        else:
            lines.append("nothing scoreable yet -- no rates are reported")

        if self.inconclusive:
            lines.append(
                "  " + str(self.inconclusive)
                + " decision(s) could not be checked and are excluded from"
                " every rate above"
            )

        if any(b.count for b in self.buckets):
            lines.append("")
            lines.append("calibration        said     actual    n")
            for bucket in self.buckets:
                if not bucket.count:
                    continue
                lines.append(
                    "  "
                    + (str(bucket.low) + "-" + str(min(bucket.high, 1.0))).ljust(16)
                    + str(round(bucket.mean_confidence or 0, 2)).ljust(9)
                    + str(round((bucket.hit_rate or 0) * 100, 1)).rjust(5) + "%"
                    + str(bucket.count).rjust(5)
                )

        if self.authors:
            lines.append("")
            lines.append("voices")
            for author in self.authors:
                rate = (
                    str(round(author.hit_rate * 100, 1)) + "%"
                    if author.hit_rate is not None
                    else "no record"
                )
                lines.append(
                    "  " + author.key.ljust(20) + rate.rjust(10)
                    + "   " + str(author.scored) + " scored"
                    + (
                        ", " + str(author.inconclusive) + " unverifiable"
                        if author.inconclusive
                        else ""
                    )
                )

        if self.rules:
            lines.append("")
            lines.append("rules satisfied on decisions that later")
            for rule in self.rules:
                rate = (
                    str(round(rule.hit_rate * 100, 1)) + "% held"
                    if rule.hit_rate is not None
                    else "no record"
                )
                lines.append("  " + rule.key.ljust(20) + rate.rjust(14))

        return "\n".join(lines)


def _tally(pairs: Iterable[tuple[str, Review]]) -> tuple[Reliability, ...]:
    held: dict[str, int] = {}
    falsified: dict[str, int] = {}
    inconclusive: dict[str, int] = {}
    keys: list[str] = []

    for key, review in pairs:
        if key not in held:
            keys.append(key)
            held[key] = falsified[key] = inconclusive[key] = 0
        if review.result is ReviewResult.HELD:
            held[key] += 1
        elif review.result is ReviewResult.FALSIFIED:
            falsified[key] += 1
        else:
            inconclusive[key] += 1

    out = [
        Reliability(
            key=key,
            held=held[key],
            falsified=falsified[key],
            inconclusive=inconclusive[key],
        )
        for key in keys
    ]
    # Worst first: the useful end of the list is the one that needs action.
    out.sort(key=lambda r: (r.hit_rate if r.hit_rate is not None else 2.0, -r.scored, r.key))
    return tuple(out)


def build_scorecard(reviews: Iterable[Review]) -> Scorecard:
    reviews = list(reviews)
    scoreable = [r for r in reviews if r.scoreable]

    held = sum(1 for r in scoreable if r.result is ReviewResult.HELD)
    falsified = sum(1 for r in scoreable if r.result is ReviewResult.FALSIFIED)

    brier = None
    if scoreable:
        brier = sum(
            (r.confidence - (1.0 if r.result is ReviewResult.HELD else 0.0)) ** 2
            for r in scoreable
        ) / len(scoreable)

    buckets = []
    for low, high in _BUCKETS:
        members = [r for r in scoreable if low <= r.confidence < high]
        buckets.append(
            CalibrationBucket(
                low=low,
                high=high,
                count=len(members),
                mean_confidence=(
                    sum(r.confidence for r in members) / len(members) if members else None
                ),
                hit_rate=(
                    sum(1 for r in members if r.result is ReviewResult.HELD) / len(members)
                    if members
                    else None
                ),
            )
        )

    return Scorecard(
        reviewed=len(reviews),
        scored=len(scoreable),
        inconclusive=len(reviews) - len(scoreable),
        held=held,
        falsified=falsified,
        brier=brier,
        buckets=tuple(buckets),
        authors=_tally(
            (author, review) for review in reviews for author in review.credited_authors
        ),
        rules=_tally(
            (rule, review) for review in reviews for rule in review.credited_rules
        ),
    )
