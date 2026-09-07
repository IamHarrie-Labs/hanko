"""exit_liquidity -- can you actually get out, and what does it cost?

THE GAP THIS FILLS

The six tools on the real catalog all answer whether a token is worth
entering. `analyze_token` and `deep_analysis` say what it is doing,
`compare_tokens` ranks candidates, `scan_market` and `market_overview`
survey the field. Nothing anywhere says whether a position can be
*closed* at the size you hold, or what closing it costs.

That is the number that turns research into a trade. A token can clear
every measured signal and still be a trap: a pool where exiting $50k
moves the price 18% is not a safe position, it is a slow one. Position
size without exit cost is a guess with a number attached.

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

  A missing input silences the answer it feeds, and only that one. If
  liquidity is unavailable the slippage fields are null and the verdict
  is `unknown`. They are never zero, because a zero here reads as "free
  to exit" -- the most dangerous possible fabrication in this particular
  tool. Time to exit does not take liquidity as an input, so it is still
  answered: refusing it as well would be over-refusal, which costs a
  caller a real answer just as surely as a fabricated one misleads them.
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
    # What the market's own flow absorbs in an hour at the participation
    # cap. Volume-derived, so it survives the missing depth figure.
    hourly_capacity_usd: float | None = None
    # Share of the token's whole value traded per day, and the price
    # movement the position is exposed to while it unwinds.
    turnover_pct: float | None = None
    position_pct_of_cap: float | None = None
    drift_exposure_pct: float | None = None

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
            "hourly_capacity_usd": (
                round(self.hourly_capacity_usd, 2)
                if self.hourly_capacity_usd is not None
                else None
            ),
            "turnover_pct": (
                round(self.turnover_pct, 3) if self.turnover_pct is not None else None
            ),
            "position_pct_of_cap": (
                round(self.position_pct_of_cap, 4)
                if self.position_pct_of_cap is not None
                else None
            ),
            "drift_exposure_pct": (
                round(self.drift_exposure_pct, 2)
                if self.drift_exposure_pct is not None
                else None
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
        # The facts this ran on, shown rather than merely traced. Without
        # them two different tokens can print an identical report -- the
        # figures that actually distinguish them were fetched, recorded
        # with the key path they came from, and then never displayed.
        by_field = {i.field: i.value for i in self.inputs}
        observed = []
        if by_field.get("price_usd") is not None:
            observed.append("price $" + _price(by_field["price_usd"]))
        if by_field.get("volume_24h_usd") is not None:
            observed.append("24h volume $" + _money(by_field["volume_24h_usd"]))
        if observed:
            tools = sorted({
                str(i.source).split(":", 1)[0]
                for i in self.inputs
                if i.value is not None and i.source
            })
            line = "  " + " · ".join(observed)
            if tools:
                line += "  (" + ", ".join(tools) + ")"
            lines.append(line)
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
            # "or" only reads correctly as the alternative to a cost figure
            # printed above. With no estimate, this is the sole answer.
            lead = "  or exit over " if self.estimate else "  exit over "
            lines.append(
                lead + _duration(self.hours_to_exit)
                + " at " + str(round(self.participation * 100)) + "% of volume"
            )
        if self.hourly_capacity_usd is not None:
            lines.append(
                "  this market absorbs $" + _money(self.hourly_capacity_usd)
                + " per hour at that cap"
            )
        if self.drift_exposure_pct is not None:
            # The other half of the trade-off. A slow exit was priced at
            # zero until this line existed, which made "just take longer"
            # look free when it is only differently expensive.
            #
            # A near-instant exit really is near-zero drift, but printing
            # "~0.0%" reads as a computed zero -- a measured smallness
            # dressed up as certainty. Said in words instead.
            shown = (
                "under 0.1%"
                if self.drift_exposure_pct < 0.1
                else "~" + str(round(self.drift_exposure_pct, 1)) + "%"
            )
            lines.append(
                "  waiting that long is exposed to " + shown
                + " price drift at this market's volatility"
            )
        if self.turnover_pct is not None:
            line = "  turnover " + str(round(self.turnover_pct, 1)) + "% of market cap per day"
            if self.position_pct_of_cap is not None:
                share = (
                    "under 0.01%"
                    if self.position_pct_of_cap < 0.01
                    else str(round(self.position_pct_of_cap, 3)) + "%"
                )
                line += "; this position is " + share + " of cap"
            lines.append(line)
        for warning in self.warnings:
            lines.append("  ! " + warning)
        for gap in self.gaps:
            lines.append("  ? " + gap)
        lines.append("  modelled with " + MODEL_ID + ", not observed")
        return "\n".join(lines)


def _money(value: float) -> str:
    return format(round(value), ",")


def _price(value: float) -> str:
    """Prices here span nine orders of magnitude, from BTC to a memecoin.

    Rounding to whole dollars would print a real quoted price of
    $0.0000034 as $0 -- a measured number destroyed by its own formatting.
    """
    if value >= 1:
        return format(value, ",.2f")
    if value >= 0.01:
        return format(value, ".4f")
    return format(value, ".8f").rstrip("0")


def _duration(hours: float) -> str:
    """Read a duration at the scale it actually has.

    A deep pool and a modest size give a genuinely tiny number, and
    rounding that to "0.0h" reads as no answer at all rather than as the
    answer "immediately" -- losing real information to formatting.
    """
    if hours >= 48:
        return str(round(hours / 24, 1)) + " days"
    if hours >= 1:
        return str(round(hours, 1)) + "h"
    minutes = hours * 60
    if minutes >= 1:
        return str(round(minutes)) + " min"
    return "under a minute"


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
    cap = facts.market_cap_usd
    atr = facts.atr_14_pct

    turnover_pct = (
        model.turnover(volume, cap) * 100
        if volume is not None and cap and cap > 0
        else None
    )
    position_pct_of_cap = (
        size_usd / cap * 100 if size_usd and cap and cap > 0 else None
    )

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

    # --- no liquidity, no price-impact numbers ---------------------------
    if liquidity is None:
        # Time-to-exit is a function of size, volume and participation --
        # pool depth is not one of its inputs. Withholding it because a
        # *different* input is missing would be over-refusal: as much a
        # reporting failure as claiming a number that isn't supported.
        # The price-impact question stays unknown; this one is answered.
        patient_hours = (
            model.hours_to_exit(size_usd, volume, participation)
            if size_usd and volume
            else None
        )
        capacity = (
            model.size_for_hours(1.0, volume, participation) if volume else None
        )
        if patient_hours is not None or capacity is not None:
            notes.append(
                "time to exit and hourly capacity are measured from live 24h "
                "volume and do not depend on pool depth; they are answered here "
                "while price impact stays unknown"
            )
        notes.append("no exit cost can be modelled without pool liquidity")
        return Report(
            token=token,
            as_of=as_of,
            verdict=Verdict.UNKNOWN,
            confidence=Confidence.NONE,
            requested_size_usd=size_usd,
            estimate=None,
            max_size_usd={"1pct": None, "3pct": None, "at_ceiling": None},
            hours_to_exit=patient_hours,
            curve=(),
            max_slippage=max_slippage,
            participation=participation,
            inputs=inputs,
            gaps=tuple(gaps),
            notes=tuple(notes),
            hourly_capacity_usd=capacity,
            turnover_pct=turnover_pct,
            position_pct_of_cap=position_pct_of_cap,
            drift_exposure_pct=(
                model.drift_exposure(patient_hours, atr)
                if patient_hours and atr
                else None
            ),
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
        hourly_capacity_usd=(
            model.size_for_hours(1.0, volume, participation) if volume else None
        ),
        turnover_pct=turnover_pct,
        position_pct_of_cap=position_pct_of_cap,
        drift_exposure_pct=(
            model.drift_exposure(hours, atr) if hours and atr else None
        ),
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
