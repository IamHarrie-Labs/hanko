"""The user's stated risk limits and thresholds.

Every number the engine uses to reach a verdict lives here, and the policy
is hashed into the Decision Record. That matters for two reasons:

  A replayed decision uses the policy that was in force at the time, not
  whatever the file says today.

  A change of mind is visible. Loosening a threshold after a loss produces
  a different policy digest, so it cannot be passed off as the rule that
  was always there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from ..provenance import digest


@dataclass(frozen=True, slots=True)
class Policy:
    # --- entry thresholds -------------------------------------------------
    min_independent_voices: int = 2
    min_mean_conviction: float = 0.35
    min_evidence_quality: float = 0.40

    # --- risk limits ------------------------------------------------------
    max_position_fraction: float = 0.05  # of book, at perfect evidence
    min_position_fraction: float = 0.005  # below this, take nothing at all
    max_exit_slippage: float = 0.03  # ceiling used by the exit-liquidity gate
    max_correlated_exposure: float = 0.40  # portfolio concentration ceiling
    min_safety_score: float = 0.50  # hard floor when safety data exists

    # --- evidence quality weights ----------------------------------------
    # Combined as a weighted geometric mean, so a component at zero takes
    # the whole score to zero. Missing safety data cannot be averaged away
    # by an abundance of enthusiastic posts.
    weight_completeness: float = 1.0
    weight_freshness: float = 1.0
    weight_corroboration: float = 1.0
    weight_independence: float = 1.5

    # --- freshness --------------------------------------------------------
    freshness_half_life_hours: float = 6.0

    # --- pre-registration -------------------------------------------------
    review_horizon: timedelta = timedelta(hours=72)

    # --- convergence ------------------------------------------------------
    echo_window_minutes: int = 90
    echo_similarity: float = 0.6

    label: str = "default"
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "min_independent_voices": self.min_independent_voices,
            "min_mean_conviction": self.min_mean_conviction,
            "min_evidence_quality": self.min_evidence_quality,
            "max_position_fraction": self.max_position_fraction,
            "min_position_fraction": self.min_position_fraction,
            "max_exit_slippage": self.max_exit_slippage,
            "max_correlated_exposure": self.max_correlated_exposure,
            "min_safety_score": self.min_safety_score,
            "weight_completeness": self.weight_completeness,
            "weight_freshness": self.weight_freshness,
            "weight_corroboration": self.weight_corroboration,
            "weight_independence": self.weight_independence,
            "freshness_half_life_hours": self.freshness_half_life_hours,
            "review_horizon_seconds": int(self.review_horizon.total_seconds()),
            "echo_window_minutes": self.echo_window_minutes,
            "echo_similarity": self.echo_similarity,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Policy":
        d = dict(d)
        horizon = timedelta(seconds=d.pop("review_horizon_seconds"))
        return cls(review_horizon=horizon, **d)

    @property
    def policy_digest(self) -> str:
        return digest(self.to_dict())
