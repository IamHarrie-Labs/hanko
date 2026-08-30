"""exit_liquidity -- can you actually get out, and what does it cost?

THE GAP THIS FILLS

The seven published tools answer whether a token is worth entering.
`check_safety` says it is not a scam. `analyze_token` and `deep_analysis`
say what it is doing. Nothing anywhere says whether a position can be
*closed* at the size you hold, or what closing it costs.

That is the number that turns research into a trade. A token can pass
every safety check and still be a trap: a 92 safety score on a pool where
exiting $50k moves the price 18% is not a safe position, it is a slow one.
Position size without exit cost is a guess with a number attached.

WHAT IT RETURNS

    exit cost at the size you asked about
    the largest size that clears your slippage ceiling
    how long a patient exit would take instead
    a cost curve across sizes scaled to the pool
    every assumption behind those figures
    every input it wanted and did not get

HONESTY CONVENTION

Two rules, both stricter than the platform requires.

  Modelled is not measured. No order book is observed anywhere in this
  skill, so no figure it returns is presented as observed and confidence
  never reads higher than `moderate`. The model, its assumptions, and the
  point past which it stops being valid all travel with the answer.

  A missing input produces no number. If liquidity is unavailable the
  slippage fields are null and the verdict is `unknown`. They are never
  zero, because a zero here reads as "free to exit" -- the most dangerous
  possible fabrication in this particular tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ...decision.record import MarketFacts
from ...provenance import to_iso, utcnow
from . import model
from .model import ASSUMPTIONS, MODEL_ID, Confidence, Estimate, Verdict

SKILL_NAME = "exit_liquidity"
SKILL_VERSION = "1.0.0"

DEFAULT_MAX_SLIPPAGE = 0.03
DEFAULT_PARTICIPATION = 0.10


@dataclass(frozen=True, slots=True)
class InputTrace:
    """One number the skill used, and where it came from."""

    field: str
    value: float | None
    source: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "value": self.value, "source": self.source}


@dataclass(frozen=True, slots=True)
class Report:
    token: str
    as_of: datetime
    verdict: Verdict
    confidence: Confidence

    requested_size_usd: float | None
    estimate: Estimate | None
    max_size_usd: dict[str, float | None]
    hours_to_exit: float | None
    curve: tuple[Estimate, ...]

    max_slippage: float
    participation: float

    inputs: tuple[InputTrace, ...]
    gaps: tuple[str, ...]
    notes: tuple[str, ...]

    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": SKILL_NAME,
            "version": SKILL_VERSION,
            "token": self.token,
            "as_of": to_iso(self.as_of),
            "verdict": self.verdict.value,
            "confidence": self.confidence.value,
            "requested_size_usd": self.requested_size_usd,
            "estimate": self.estimate.to_dict() if self.estimate else None,
            "max_size_usd": self.max_size_usd,
            "hours_to_exit": (
                round(self.hours_to_exit, 2) if self.hours_to_exit is not None else None
            ),
            "curve": [e.to_dict() for e in self.curve],
            "parameters": {
                "max_slippage_pct": round(self.max_slippage * 100, 4),
                "participation_pct": round(self.participation * 100, 4),
            },
            "model": {"id": MODEL_ID, "assumptions": list(ASSUMPTIONS)},
            "inputs": [i.to_dict() for i in self.inputs],
            "gaps": list(self.gaps),
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }

    def explain(self) -> str:
        lines = [
            self.verdict.value.upper() + "  " + self.token
            + "  confidence " + self.confidence.value,
        ]
        if self.estimate:
            lines.append(
                "  exiting $" + _money(self.estimate.size_usd)
                + " costs " + str(round(self.estimate.slippage * 100, 2)) + "%"
                + "  ($" + _money(self.estimate.cost_usd) + ")"
            )
        labels = {
            "1pct": "1% slippage",
            "3pct": "3% slippage",
            "at_ceiling": "your " + str(round(self.max_slippage * 100, 2)) + "% ceiling",
        }
        for key, value in self.max_size_usd.items():
            if value is not None:
                lines.append(
                    "  largest exit at " + labels.get(key, key) + ": $" + _money(value)
                )
        if self.hours_to_exit is not None:
            lines.append(
                "  or exit over " + str(round(self.hours_to_exit, 1))
                + "h at " + str(round(self.participation * 100)) + "% of volume"
            )
        for warning in self.warnings:
            lines.append("  ! " + warning)
        for gap in self.gaps:
            lines.append("  ? " + gap)
        lines.append("  modelled with " + MODEL_ID + ", not observed")
        return "\n".join(lines)


def _money(value: float) -> str:
    return format(round(value), ",")


def assess(
    token: str,
    facts: MarketFacts,
    *,
    size_usd: float | None = None,
    max_slippage: float = DEFAULT_MAX_SLIPPAGE,
    participation: float = DEFAULT_PARTICIPATION,
    sources: dict[str, str] | None = None,
    as_of: datetime | None = None,
) -> Report:
    """Pure. Same facts and parameters in, same report out.

    `sources` maps a fact name to the tool and key path it was read from,
    so every number in the report can be traced to a payload rather than
    taken on trust.
    """
    as_of = as_of or utcnow()
    sources = sources or {}
    token = token.upper()

    liquidity = facts.liquidity_usd
    volume = facts.volume_24h_usd

    inputs = (
        InputTrace("liquidity_usd", liquidity, sources.get("liquidity_usd")),
        InputTrace("volume_24h_usd", volume, sources.get("volume_24h_usd")),
        InputTrace("price_usd", facts.price_usd, sources.get("price_usd")),
    )

    gaps: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    if liquidity is None:
        gaps.append(
            "liquidity_usd unavailable; exit cost cannot be modelled and is "
            "reported as null rather than zero"
        )
    elif liquidity <= 0:
        gaps.append("liquidity_usd reported as " + str(liquidity) + ", which is unusable")
        liquidity = None

    if volume is None:
        gaps.append("volume_24h_usd unavailable; time to exit cannot be estimated")

    # --- no liquidity, no numbers ----------------------------------------
    if liquidity is None:
        return Report(
            token=token,
            as_of=as_of,
            verdict=Verdict.UNKNOWN,
            confidence=Confidence.NONE,
            requested_size_usd=size_usd,
            estimate=None,
            max_size_usd={"1pct": None, "3pct": None, "at_ceiling": None},
            hours_to_exit=None,
            curve=(),
            max_slippage=max_slippage,
            participation=participation,
            inputs=inputs,
            gaps=tuple(gaps),
            notes=("no exit estimate is possible without pool liquidity",),
        )

    # --- the estimate ----------------------------------------------------
    estimate = model.estimate(size_usd, liquidity) if size_usd else None

    max_sizes = {
        "1pct": round(model.size_for_slippage(0.01, liquidity), 2),
        "3pct": round(model.size_for_slippage(0.03, liquidity), 2),
        "at_ceiling": round(model.size_for_slippage(max_slippage, liquidity), 2),
    }

    hours = (
        model.hours_to_exit(size_usd, volume, participation)
        if size_usd and volume
        else None
    )

    ladder = model.default_ladder(liquidity)
    curve = model.curve(liquidity, ladder)

    # --- verdict ---------------------------------------------------------
    if estimate is None:
        verdict = Verdict.UNKNOWN
        notes.append("no size requested; the curve and ceilings still apply")
    elif estimate.slippage <= max_slippage:
        verdict = Verdict.OK
    elif estimate.slippage <= max_slippage * 2:
        verdict = Verdict.TIGHT
    else:
        verdict = Verdict.ILLIQUID

    # --- confidence ------------------------------------------------------
    confidence = Confidence.MODERATE

    if estimate and not estimate.within_model:
        confidence = Confidence.LOW
        warnings.append(
            "this exit is " + str(round(estimate.pool_fraction * 100, 1))
            + "% of the pool, past the " + str(round(model.MODEL_VALIDITY_LIMIT * 100))
            + "% point where a constant-product curve stops describing a real "
            "venue; treat the figure as a floor on the true cost"
        )

    if not sources.get("liquidity_usd"):
        confidence = Confidence.LOW
        notes.append(
            "the liquidity figure carries no source path, so it could not be "
            "traced back to a specific tool response"
        )

    if volume and liquidity and volume < liquidity * 0.02:
        warnings.append(
            "24h volume is under 2% of pool liquidity; the pool may be deep but "
            "inactive, and a patient exit could take far longer than modelled"
        )

    notes.append(
        "confidence never exceeds 'moderate': no venue order book is observed "
        "anywhere in this skill"
    )

    return Report(
        token=token,
        as_of=as_of,
        verdict=verdict,
        confidence=confidence,
        requested_size_usd=size_usd,
        estimate=estimate,
        max_size_usd=max_sizes,
        hours_to_exit=hours,
        curve=curve,
        max_slippage=max_slippage,
        participation=participation,
        inputs=inputs,
        gaps=tuple(gaps),
        notes=tuple(notes),
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Tool contract
# ---------------------------------------------------------------------------

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["token"],
    "additionalProperties": False,
    "properties": {
        "token": {
            "type": "string",
            "description": "Token symbol to assess, e.g. SOL.",
        },
        "size_usd": {
            "type": "number",
            "minimum": 0,
            "description": (
                "Position size in USD to price an exit for. Omit to receive "
                "the ceilings and cost curve without a specific quote."
            ),
        },
        "max_slippage_pct": {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
            "default": DEFAULT_MAX_SLIPPAGE * 100,
            "description": "Acceptable price impact when exiting, in percent.",
        },
        "participation_pct": {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
            "default": DEFAULT_PARTICIPATION * 100,
            "description": (
                "Share of 24h volume you are willing to be while exiting "
                "patiently. Used for the time-to-exit estimate."
            ),
        },
    },
}

DESCRIPTION = (
    "Estimate what it costs to exit a position and the largest size that "
    "clears a given slippage ceiling. Returns a modelled figure with its "
    "assumptions attached, never an observed one, and returns null rather "
    "than zero when pool liquidity is unavailable."
)


def describe() -> dict[str, Any]:
    """The MCP tool definition, ready to register on a server."""
    return {
        "name": SKILL_NAME,
        "description": DESCRIPTION,
        "inputSchema": INPUT_SCHEMA,
    }


def call(arguments: dict[str, Any], facts: MarketFacts, **kwargs: Any) -> dict[str, Any]:
    """Tool-call entry point: schema arguments in, JSON-serialisable out."""
    return assess(
        arguments["token"],
        facts,
        size_usd=arguments.get("size_usd"),
        max_slippage=arguments.get("max_slippage_pct", DEFAULT_MAX_SLIPPAGE * 100) / 100,
        participation=arguments.get("participation_pct", DEFAULT_PARTICIPATION * 100) / 100,
        **kwargs,
    ).to_dict()
