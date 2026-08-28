"""Extracting market facts from RYO tool responses. Pure.

The exact response shapes of the seven research tools are not yet confirmed
against a live endpoint, so extraction is structural rather than path-based:
each field is matched against a list of plausible key names, anywhere in the
payload. That way the envelope can move without invalidating stored
snapshots, and a shape that was never anticipated fails visibly instead of
silently returning a zero.

Two rules hold regardless of what the real schema turns out to be.

  A field that is not found stays None. It becomes a gap, the gap lowers
  evidence quality, and quality lowers position size. Nothing is defaulted,
  because a defaulted number is a fabricated one and the platform's honesty
  convention forbids exactly that.

  Every number that IS found records the key it came from. A fact in a
  Decision Record can therefore be traced to a key in a payload addressed
  by its own hash -- not merely asserted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from ..decision.record import MarketFacts

# Candidate key names per field, in priority order. Additive on purpose:
# adding a real key name once the schema is confirmed does not invalidate
# anything already stored.
_CANDIDATES: dict[str, tuple[str, ...]] = {
    "price_usd": ("price_usd", "priceUsd", "price", "current_price", "last_price"),
    "volume_24h_usd": (
        "volume_24h_usd",
        "volume24hUsd",
        "volume_24h",
        "volume24h",
        "total_volume",
        "volume",
    ),
    "liquidity_usd": (
        "liquidity_usd",
        "liquidityUsd",
        "liquidity",
        "total_liquidity",
        "tvl_usd",
        "tvl",
    ),
    "safety_score": ("safety_score", "safetyScore", "safety_rating", "safety"),
}


@dataclass(frozen=True, slots=True)
class Extraction:
    """What was found, what was not, and where each number came from."""

    facts: MarketFacts
    found: dict[str, str] = field(default_factory=dict)  # field -> key it matched
    missing: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": self.facts.to_dict(),
            "found": self.found,
            "missing": list(self.missing),
            "notes": list(self.notes),
        }


def _walk(node: Any, path: str = "") -> Iterator[tuple[str, str, Any]]:
    """Yield (key, path, value) for every mapping entry in the payload."""
    if isinstance(node, dict):
        for key, value in node.items():
            here = path + "." + key if path else key
            yield key, here, value
            yield from _walk(value, here)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, path + "[" + str(index) + "]")


def _as_number(value: Any) -> float | None:
    """Accept a number, or a numeric string. Reject everything else.

    Booleans are rejected deliberately: in Python `True` is an int, and a
    safety check that answered `true` must not silently become a score of
    1.0. That is a verdict, not a measurement, and pretending otherwise
    would manufacture the most consequential number in the system.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", "").lstrip("$"))
        except ValueError:
            return None
    return None


def extract_market_facts(
    subject: str,
    payloads: dict[str, Any],
    *,
    snapshot_id: str | None = None,
) -> Extraction:
    """Pull MarketFacts out of one or more tool payloads.

    `payloads` maps tool name to that tool's stored payload, so a single
    set of facts can be assembled from analyze_token, deep_analysis and
    check_safety together while still recording which tool supplied what.
    """
    found: dict[str, str] = {}
    values: dict[str, float] = {}
    notes: list[str] = []

    for tool, payload in sorted(payloads.items()):
        for target, candidates in _CANDIDATES.items():
            if target in values:
                continue
            best: tuple[int, str, float] | None = None
            for key, path, value in _walk(payload):
                if key not in candidates:
                    continue
                number = _as_number(value)
                if number is None:
                    continue
                rank = candidates.index(key)
                # Prefer the most specific key name, and among equals the
                # shallowest path -- a top-level `price` beats one buried
                # in a list of historical points.
                if best is None or (rank, path.count(".")) < (best[0], best[1].count(".")):
                    best = (rank, path, number)
            if best is not None:
                values[target] = best[2]
                found[target] = tool + ":" + best[1]

    safety = values.get("safety_score")
    if safety is not None and safety > 1.0:
        if safety <= 100.0:
            values["safety_score"] = safety / 100.0
            notes.append(
                "safety_score arrived as " + str(safety)
                + " and was read as a 0-100 scale"
            )
        else:
            # Out of every range we can interpret. Dropped rather than
            # clamped: a clamped safety score is an invented one.
            del values["safety_score"]
            found.pop("safety_score", None)
            notes.append(
                "safety_score of " + str(safety)
                + " fits no scale we recognise and was discarded"
            )

    facts = MarketFacts(
        subject=subject.upper(),
        price_usd=values.get("price_usd"),
        volume_24h_usd=values.get("volume_24h_usd"),
        liquidity_usd=values.get("liquidity_usd"),
        safety_score=values.get("safety_score"),
        snapshot_id=snapshot_id,
    )
    return Extraction(
        facts=facts,
        found=found,
        missing=facts.missing,
        notes=tuple(notes),
    )
