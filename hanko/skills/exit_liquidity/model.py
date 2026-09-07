"""The exit-cost model, and the assumptions it rests on.

The honest problem this skill has to solve: nobody hands out order books.
What is available is pool liquidity and 24h volume, which is enough to
*model* an exit but not enough to *observe* one. Those are different
claims, and conflating them is how a position gets sized off a number
that was never measured.

So every figure this module produces is labelled `modelled`, carries the
model that produced it, and lists the assumptions in the response itself.
A caller that wants to disagree with the model can see exactly what to
disagree with.

THE MODEL (cpmm_v1)

Constant-product pool, x * y = k. Selling dx of the base token returns
dy = y*dx/(x+dx), so against the mid price the shortfall is

    slippage = dx / (x + dx) = f / (1 + f)      where f = dx / x

Working in USD: reported pool liquidity is taken to be total value locked,
which for a balanced two-sided pool is twice the value of either side. So
selling S dollars of notional gives

    f = S / (liquidity_usd / 2) = 2S / liquidity_usd

Every one of those steps is an assumption that can be wrong -- the venue
may be a stableswap or a CLMM, liquidity may be spread across pools, TVL
may be reported per-side. They are stated, not buried, and the model is
declared invalid past the point where they stop holding.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

MODEL_ID = "cpmm_v1"

# Past this fraction of the pool, a constant-product curve stops being a
# defensible approximation of a real venue: routers split, other pools
# absorb flow, and market makers step away. The tool says so rather than
# extrapolating a number it does not believe.
MODEL_VALIDITY_LIMIT = 0.25

ASSUMPTIONS = (
    "pool behaves as constant-product (x*y=k)",
    "reported liquidity is total value locked, i.e. twice one side",
    "all liquidity is reachable in a single route",
    "no fees, no MEV, no price movement during the exit",
    "mid price at the time of the quote",
)


class Confidence(str, Enum):
    # Deliberately has no HIGH. No venue-level order book is observed
    # anywhere in this skill, so nothing it returns has earned that word.
    MODERATE = "moderate"
    LOW = "low"
    NONE = "none"


class Verdict(str, Enum):
    OK = "ok"  # exits inside the caller's slippage ceiling
    TIGHT = "tight"  # exits, but above the ceiling
    ILLIQUID = "illiquid"  # exit cost is severe at this size
    UNKNOWN = "unknown"  # not enough input to say anything


def slippage_for(size_usd: float, liquidity_usd: float) -> float:
    """Fraction of notional lost to price impact. 0.0 to 1.0."""
    if liquidity_usd <= 0 or size_usd <= 0:
        return 0.0
    f = (2.0 * size_usd) / liquidity_usd
    return f / (1.0 + f)


def size_for_slippage(target: float, liquidity_usd: float) -> float:
    """Largest notional whose modelled slippage stays at or under `target`."""
    if liquidity_usd <= 0 or target <= 0:
        return 0.0
    if target >= 1.0:
        return float("inf")
    f = target / (1.0 - target)
    return f * liquidity_usd / 2.0


def pool_fraction(size_usd: float, liquidity_usd: float) -> float:
    """How much of the pool this exit represents. Drives model validity."""
    if liquidity_usd <= 0:
        return float("inf")
    return (2.0 * size_usd) / liquidity_usd


def hours_to_exit(
    size_usd: float,
    volume_24h_usd: float,
    participation: float,
) -> float | None:
    """Hours to unwind while staying under `participation` of daily volume.

    The alternative to paying the slippage above is to take longer. Both
    numbers are reported because they are the same trade-off seen from two
    sides, and a position that can only be exited over days is a different
    position from one that exits in an hour.
    """
    if volume_24h_usd <= 0 or participation <= 0 or size_usd <= 0:
        return None
    return 24.0 * size_usd / (volume_24h_usd * participation)


def size_for_hours(
    hours: float,
    volume_24h_usd: float,
    participation: float,
) -> float | None:
    """Largest notional that unwinds within `hours` at the same cap.

    The inverse of hours_to_exit, and the only capacity figure available
    when no pool depth is published: it asks what the market's own flow
    can absorb rather than what a pool would charge. That makes it the
    one number here that separates a deep market from a thin one when
    the depth figure is missing -- $45m an hour and $500k an hour are
    the same "under a minute" for a small enough position, and very
    different markets to hold a real one in.
    """
    if volume_24h_usd <= 0 or participation <= 0 or hours <= 0:
        return None
    return hours * volume_24h_usd * participation / 24.0


def turnover(volume_24h_usd: float, market_cap_usd: float) -> float | None:
    """Share of the token's whole value that changes hands in a day.

    The standard liquidity proxy, and the one measure of depth available
    when no pool is published: a market turning over 46% of its own cap
    daily and one turning over 3% are not the same place to hold size,
    however similar their dollar volumes look.
    """
    if market_cap_usd <= 0 or volume_24h_usd < 0:
        return None
    return volume_24h_usd / market_cap_usd


def drift_exposure(hours: float, atr_daily_pct: float) -> float | None:
    """Price movement a position is exposed to while it unwinds, percent.

    The skill's whole trade-off is "pay slippage now, or take longer" --
    but taking longer was priced at zero, which is its own quiet
    fabrication. Volatility accumulates with the square root of time, so
    a day's ATR over T days is ATR * sqrt(T). This is exposure, not an
    expected loss: it is as likely to move for you as against you, and
    it is a scale, not a forecast.
    """
    if hours <= 0 or atr_daily_pct <= 0:
        return None
    return atr_daily_pct * math.sqrt(hours / 24.0)


@dataclass(frozen=True, slots=True)
class Estimate:
    size_usd: float
    slippage: float
    cost_usd: float
    proceeds_usd: float
    pool_fraction: float
    within_model: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "size_usd": round(self.size_usd, 2),
            "slippage_pct": round(self.slippage * 100, 4),
            "cost_usd": round(self.cost_usd, 2),
            "proceeds_usd": round(self.proceeds_usd, 2),
            "pool_fraction_pct": round(self.pool_fraction * 100, 3),
            "basis": "modelled",
            "model": MODEL_ID,
            "within_model_validity": self.within_model,
        }


def estimate(size_usd: float, liquidity_usd: float) -> Estimate:
    slip = slippage_for(size_usd, liquidity_usd)
    fraction = pool_fraction(size_usd, liquidity_usd)
    cost = size_usd * slip
    return Estimate(
        size_usd=size_usd,
        slippage=slip,
        cost_usd=cost,
        proceeds_usd=size_usd - cost,
        pool_fraction=fraction,
        within_model=fraction <= MODEL_VALIDITY_LIMIT,
    )


def curve(liquidity_usd: float, sizes: tuple[float, ...]) -> tuple[Estimate, ...]:
    return tuple(estimate(size, liquidity_usd) for size in sorted(sizes))


def default_ladder(liquidity_usd: float) -> tuple[float, ...]:
    """A size ladder scaled to the pool, so the curve is informative.

    A fixed dollar ladder tells you nothing useful about both a $50k pool
    and a $50m one.
    """
    if liquidity_usd <= 0:
        return ()
    return tuple(
        round(liquidity_usd * fraction / 2.0, 2)
        for fraction in (0.005, 0.01, 0.025, 0.05, 0.10, 0.25)
    )
