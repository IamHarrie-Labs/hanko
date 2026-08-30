"""Evidence quality, and the gaps that reduce it.

This is where the honesty convention stops being an error-handling rule and
becomes the risk model. Position size is a function of how good the evidence
is, so a source that dropped shrinks the position mechanically -- not
because a rule says "if safety is unavailable then skip", but because a
missing input lowers quality, and quality sets size.

The four components combine as a weighted GEOMETRIC mean, chosen on purpose:
a component at zero takes the whole score to zero. Missing safety data
cannot be averaged away by an abundance of enthusiastic posts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from ..evidence import Evidence
from .convergence import ConvergenceReport
from .policy import Policy


class GapKind(str, Enum):
    SOURCE_FAILED = "source_failed"  # asked, did not answer
    COVERAGE_UNKNOWN = "coverage_unknown"  # search tool, recall unprovable
    COVERAGE_PARTIAL = "coverage_partial"  # known to be missing part of the window
    MARKET_FIELD_MISSING = "market_field_missing"
    NO_TIMESTAMP = "no_timestamp"  # evidence that cannot be placed in time


@dataclass(frozen=True, slots=True)
class Gap:
    """Something the agent asked for and did not get."""

    kind: GapKind
    subject: str
    detail: str
    snapshot_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "subject": self.subject,
            "detail": self.detail,
            "snapshot_id": self.snapshot_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Gap":
        return cls(
            kind=GapKind(d["kind"]),
            subject=d["subject"],
            detail=d["detail"],
            snapshot_id=d.get("snapshot_id"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceQuality:
    completeness: float
    freshness: float
    corroboration: float
    independence: float
    overall: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "completeness": round(self.completeness, 6),
            "freshness": round(self.freshness, 6),
            "corroboration": round(self.corroboration, 6),
            "independence": round(self.independence, 6),
            "overall": round(self.overall, 6),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvidenceQuality":
        return cls(
            completeness=d["completeness"],
            freshness=d["freshness"],
            corroboration=d["corroboration"],
            independence=d["independence"],
            overall=d["overall"],
        )


def _weighted_geometric_mean(pairs: list[tuple[float, float]]) -> float:
    """pairs of (value, weight). Any value at zero returns zero."""
    total_weight = sum(w for _, w in pairs)
    if total_weight <= 0:
        return 0.0
    if any(v <= 0.0 for v, _ in pairs):
        return 0.0
    log_sum = sum(w * math.log(min(1.0, v)) for v, w in pairs)
    return math.exp(log_sum / total_weight)


def assess_quality(
    *,
    evidence: list[Evidence],
    convergence: ConvergenceReport,
    gaps: list[Gap],
    sources_requested: int,
    market_fields_required: int,
    market_fields_present: int,
    as_of: datetime,
    policy: Policy,
) -> EvidenceQuality:
    failed = sum(1 for g in gaps if g.kind is GapKind.SOURCE_FAILED)
    partial = sum(1 for g in gaps if g.kind is GapKind.COVERAGE_PARTIAL)

    # Completeness: what fraction of what we asked for actually arrived.
    # A partially covered source counts as half a source, which is a
    # judgement call, but a consistently applied one.
    if sources_requested <= 0:
        source_ratio = 0.0
    else:
        answered = sources_requested - failed - 0.5 * partial
        source_ratio = max(0.0, answered / sources_requested)

    field_ratio = (
        market_fields_present / market_fields_required
        if market_fields_required > 0
        else 1.0
    )
    completeness = max(0.0, min(1.0, source_ratio * field_ratio))

    # Freshness: exponential decay on the median age of dated evidence.
    # Undated evidence is excluded here and penalised through its own gap
    # rather than being assigned an age we do not know.
    ages = sorted(
        (as_of - e.published_at).total_seconds() / 3600.0
        for e in evidence
        if e.published_at is not None
    )
    if not ages:
        freshness = 0.0
    else:
        median = ages[len(ages) // 2]
        freshness = min(1.0, 2.0 ** (-max(0.0, median) / policy.freshness_half_life_hours))

    # Corroboration: distinct authors, saturating at three. One voice is a
    # tip; three is a pattern; twenty is not seven times better than three.
    corroboration = min(1.0, convergence.distinct_authors / 3.0)

    # Independence: how much of that agreement survived the echo check.
    independence = convergence.independence_ratio

    overall = _weighted_geometric_mean(
        [
            (completeness, policy.weight_completeness),
            (freshness, policy.weight_freshness),
            (corroboration, policy.weight_corroboration),
            (independence, policy.weight_independence),
        ]
    )
    return EvidenceQuality(
        completeness=completeness,
        freshness=freshness,
        corroboration=corroboration,
        independence=independence,
        overall=overall,
    )
