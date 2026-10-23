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

Three rules, all stricter than the platform requires.

  Modelled is not measured. A figure from the constant-product model is
  labelled `modelled`, carries its assumptions and the point past which it
  stops being valid, and never reads higher than `moderate` confidence.

  Measured beats modelled, and the gap is published. When venues.py
  supplies an executable quote for the exact size, the verdict comes from
  the quote (`basis: quoted`, the only case that reaches `high`), and the
  model's own figure is kept beside it with the ratio between them -- so a
  model that is wrong is seen to be wrong, rather than silently replaced.

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
from .venues import PoolDepth, VenueEvidence, VenueQuote

SKILL_NAME = "exit_liquidity"
# 2.0.0: venue evidence (pool depth, executable quote) and RYO's public
# response envelope. 1.x answered `unknown` on every live call.
SKILL_VERSION = "2.0.0"
ENVELOPE_SCHEMA_VERSION = "1.0"

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

    # Venue evidence. `basis` says what the verdict rests on: "quoted" (an
    # executable quote for this size), "modelled" (cpmm_v1), or None.
    basis: str | None = None
    quote: VenueQuote | None = None
    depth: PoolDepth | None = None
    model_check: dict[str, Any] | None = None
    venue_failures: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": SKILL_NAME,
            "version": SKILL_VERSION,
            "token": self.token,
            "as_of": to_iso(self.as_of),
            "verdict": self.verdict.value,
            "confidence": self.confidence.value,
            "basis": self.basis,
            "venue_quote": self.quote.to_dict() if self.quote else None,
            "pool_depth": self.depth.to_dict() if self.depth else None,
            "model_check": self.model_check,
            "venue_failures": list(self.venue_failures),
            "requested_size_usd": self.requested_size_usd,
            "estimate": self.estimate.to_dict() if self.estimate else None,
            "max_size_usd": self.max_size_usd,
            "max_size_basis": (
                "modelled" if any(v is not None for v in self.max_size_usd.values()) else None
            ),
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
        if self.quote:
            lines.append(
                "  quoted: selling ~$" + _money(self.quote.size_usd) + " on "
                + self.quote.venue + " returns $" + _money(self.quote.out_usd)
                + ", " + str(round(self.quote.effective_cost * 100, 2))
                + "% under its own near-mid rate (price impact plus fees, "
                + str(self.quote.route_hops) + "-hop route)"
            )
        if self.estimate:
            prefix = "  model said " if self.quote else "  exiting $" + _money(self.estimate.size_usd) + " costs "
            lines.append(
                prefix + str(round(self.estimate.slippage * 100, 2)) + "%"
                + ("" if self.quote else "  ($" + _money(self.estimate.cost_usd) + ")")
                + (" from $" + _money(self._liquidity_used()) + " of on-chain depth"
                   if self.quote and self._liquidity_used() is not None else "")
            )
        if self.model_check and self.model_check.get("model_over_quote") is not None:
            ratio = self.model_check["model_over_quote"]
            if ratio >= 1.25:
                lines.append(
                    "  the model overstates this exit's cost " + str(round(ratio, 1))
                    + "x: the route reaches concentrated liquidity a constant-product "
                    "curve cannot see"
                )
            elif ratio <= 0.8:
                lines.append(
                    "  the model understates this exit's cost by "
                    + str(round(1 / ratio, 1)) + "x: the venue is thinner than its TVL says"
                )
            else:
                lines.append("  the model and the quote agree within 25%")
        if self.depth and self.depth.deepest:
            lines.append(
                "  depth: " + str(len(self.depth.pools_used)) + " pools on "
                + self.depth.chain + (" (" + self.depth.via + ")" if self.depth.via else "")
                + ", deepest $" + _money(self.depth.deepest.liquidity_usd)
                + (", " + str(len(self.depth.rejected)) + " rejected" if self.depth.rejected else "")
            )
        labels = {
            "1pct": "1% slippage",
            "3pct": "3% slippage",
            "at_ceiling": "your " + str(round(self.max_slippage * 100, 2)) + "% ceiling",
        }
        # The ceilings come from the model. Beside a quote that just priced
        # a bigger exit cheaper, unlabelled they read as a contradiction.
        qualifier = " (modelled, conservative)" if self.quote else ""
        for key, value in self.max_size_usd.items():
            if value is not None:
                lines.append(
                    "  largest exit at " + labels.get(key, key) + qualifier + ": $" + _money(value)
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
        for failure in self.venue_failures:
            lines.append("  ~ " + failure)
        if self.basis == "quoted":
            lines.append(
                "  verdict from an executable " + self.quote.venue + " quote at "
                + to_iso(self.as_of) + "; quotes move with the market"
            )
        else:
            lines.append("  modelled with " + MODEL_ID + ", not observed")
        return "\n".join(lines)

    def _liquidity_used(self) -> float | None:
        for trace in self.inputs:
            if trace.field == "liquidity_usd":
                return trace.value
        return None

    # ---- RYO's public response contract ------------------------------------

    def to_envelope(
        self,
        *,
        request: dict[str, Any],
        data_mode: str,
        extra_warnings: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """The same top-level fields every RYO tool returns.

        Published at ryobuild.com/docs/MCP-Builder-Guide.md ("Public response
        contract"): schema_version, tool, status, data_mode, as_of, request,
        data, summary, availability, warnings. A client written against RYO's
        six tools reads this one without a special case.

        The tool's two primary sections are price impact (quoted or modelled)
        and time to exit. Both answered is `ok`, one is `partial`, neither is
        `unavailable` -- RYO's own definitions, applied to this tool.
        """
        impact = "available" if (self.quote or self.estimate) else "unavailable"
        timing = "available" if self.hours_to_exit is not None else "unavailable"
        primary = [impact, timing] if self.requested_size_usd else [
            "available" if self.max_size_usd.get("at_ceiling") is not None else "unavailable",
            "available" if self.hourly_capacity_usd is not None else "unavailable",
        ]
        status = (
            "ok" if all(p == "available" for p in primary)
            else "unavailable" if all(p == "unavailable" for p in primary)
            else "partial"
        )
        availability = {
            "price_impact": impact,
            "venue_quote": "available" if self.quote else "unavailable",
            "pool_depth": "available" if (self.depth and self.depth.deepest) else "unavailable",
            "modelled_estimate": "available" if self.estimate else "unavailable",
            "time_to_exit": timing,
            "drift_exposure": "available" if self.drift_exposure_pct is not None else "unavailable",
        }
        return {
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "tool": SKILL_NAME,
            "status": status,
            "data_mode": data_mode,
            "as_of": to_iso(self.as_of),
            "request": request,
            "data": self.to_dict(),
            "summary": {"headline": self.headline(), "key_points": self.key_points()},
            "availability": availability,
            "warnings": list(self.warnings) + list(self.gaps) + list(self.venue_failures) + list(extra_warnings),
        }

    def headline(self) -> str:
        if self.verdict is Verdict.UNKNOWN:
            if self.requested_size_usd is None and self.max_size_usd.get("at_ceiling") is not None:
                return (
                    self.token + ": largest exit inside a " + str(round(self.max_slippage * 100, 2))
                    + "% ceiling is $" + _money(self.max_size_usd["at_ceiling"]) + " (modelled)."
                )
            return self.token + ": exit cost unknown; the inputs to price it were not available."
        cost = (
            self.quote.effective_cost if self.basis == "quoted" and self.quote
            else self.estimate.slippage if self.estimate else None
        )
        size = self.requested_size_usd or 0
        return (
            self.token + ": exiting $" + _money(size) + " costs "
            + (str(round(cost * 100, 2)) + "%" if cost is not None else "an unknown amount")
            + " (" + (self.basis or "unpriced") + "), verdict " + self.verdict.value.upper() + "."
        )

    def key_points(self) -> list[str]:
        points = []
        if self.quote:
            points.append(
                "Executable " + self.quote.venue + " quote: selling this size returns $"
                + _money(self.quote.out_usd) + ", " + str(round(self.quote.effective_cost * 100, 2))
                + "% under the venue's own near-mid rate (impact plus fees)."
            )
        if self.model_check and self.model_check.get("model_over_quote") is not None:
            points.append(
                "Constant-product model: " + str(round(self.model_check["modelled_cost_pct"], 2))
                + "% against the quote's " + str(round(self.model_check["quoted_cost_pct"], 2)) + "%."
            )
        if self.hours_to_exit is not None:
            points.append(
                "Patient exit: " + _duration(self.hours_to_exit) + " at "
                + str(round(self.participation * 100)) + "% of 24h volume."
            )
        if self.depth and self.depth.deepest:
            points.append(
                str(len(self.depth.pools_used)) + " pools used, deepest $"
                + _money(self.depth.deepest.liquidity_usd) + ", "
                + str(len(self.depth.rejected)) + " rejected."
            )
        if self.gaps:
            points.append("Missing: " + "; ".join(self.gaps))
        return points


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
    venue: VenueEvidence | None = None,
) -> Report:
    """Pure. Same facts, venue evidence and parameters in, same report out.

    `sources` maps a fact name to the tool and key path it was read from,
    so every number in the report can be traced to a payload rather than
    taken on trust.

    `venue` (from venues.py) fills what RYO's facts leave empty -- pool depth
    above all, which RYO has never returned -- and may carry an executable
    quote for the size. RYO's own figures win wherever both exist; a venue
    figure is only ever a fallback, and its source path says which it was.
    """
    as_of = as_of or utcnow()
    sources = dict(sources or {})
    token = token.upper()
    venue = venue or VenueEvidence()
    depth = venue.depth if venue.depth and venue.depth.deepest else None

    liquidity = facts.liquidity_usd
    volume = facts.volume_24h_usd
    price = facts.price_usd
    cap = facts.market_cap_usd
    atr = facts.atr_14_pct
    fallback_notes: list[str] = []

    if liquidity is None and depth and depth.total_liquidity_usd:
        liquidity = depth.total_liquidity_usd
        sources["liquidity_usd"] = depth.source + ":total_liquidity_usd"
        fallback_notes.append(
            "pool depth is the sum of " + str(len(depth.pools_used)) + " on-chain pools for the "
            "canonical contract (" + depth.source + "); RYO did not supply it"
        )
    if volume is None and depth and depth.total_volume_24h_usd:
        volume = depth.total_volume_24h_usd
        sources["volume_24h_usd"] = depth.source + ":total_volume_24h_usd"
        fallback_notes.append(
            "24h volume is on-chain only (RYO did not supply it); centralized-exchange "
            "volume is not included, so time to exit reads conservatively long"
        )
    if price is None and depth and depth.price_usd:
        price = depth.price_usd
        sources["price_usd"] = depth.source + ":volume_weighted_median_price"

    quote = venue.quote if venue.quote and size_usd else None

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
        InputTrace("price_usd", price, sources.get("price_usd")),
    )

    gaps: list[str] = []
    warnings: list[str] = []
    notes: list[str] = list(fallback_notes)

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

    # --- no liquidity and no quote: no price-impact numbers --------------
    if liquidity is None and quote is None:
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
            depth=depth,
            venue_failures=venue.failures,
        )

    # --- the modelled estimate (needs depth) -----------------------------
    estimate = model.estimate(size_usd, liquidity) if size_usd and liquidity else None

    max_sizes = (
        {
            "1pct": round(model.size_for_slippage(0.01, liquidity), 2),
            "3pct": round(model.size_for_slippage(0.03, liquidity), 2),
            "at_ceiling": round(model.size_for_slippage(max_slippage, liquidity), 2),
        }
        if liquidity
        else {"1pct": None, "3pct": None, "at_ceiling": None}
    )

    hours = (
        model.hours_to_exit(size_usd, volume, participation)
        if size_usd and volume
        else None
    )

    curve = model.curve(liquidity, model.default_ladder(liquidity)) if liquidity else ()

    def grade(cost: float) -> Verdict:
        if cost <= max_slippage:
            return Verdict.OK
        if cost <= max_slippage * 2:
            return Verdict.TIGHT
        return Verdict.ILLIQUID

    # --- verdict: a quote, when there is one, outranks the model ---------
    model_check: dict[str, Any] | None = None
    if quote is not None:
        verdict = grade(quote.effective_cost)
        basis = "quoted"
        if estimate is not None and quote.effective_cost > 0:
            model_check = {
                "modelled_cost_pct": round(estimate.slippage * 100, 4),
                "quoted_cost_pct": round(quote.effective_cost * 100, 4),
                "model_over_quote": round(estimate.slippage / quote.effective_cost, 3),
                "depth_used_usd": round(liquidity, 2),
                "note": (
                    "the constant-product model is kept beside the quote so its error "
                    "is visible; the verdict rests on the quote"
                ),
            }
    elif estimate is not None:
        verdict = grade(estimate.slippage)
        basis = "modelled"
    else:
        verdict = Verdict.UNKNOWN
        basis = None
        notes.append("no size requested; the curve and ceilings still apply")

    # --- confidence ------------------------------------------------------
    if basis == "quoted":
        confidence = Confidence.HIGH
        notes.append(
            "confidence is 'high' only because an executable quote for this exact size "
            "was observed; it holds for this moment and this venue, not for the future"
        )
    else:
        confidence = Confidence.MODERATE
        if estimate and not estimate.within_model:
            confidence = Confidence.LOW
        if liquidity is not None and not sources.get("liquidity_usd"):
            confidence = Confidence.LOW
            notes.append(
                "the liquidity figure carries no source path, so it could not be "
                "traced back to a specific tool response"
            )
        notes.append(
            "confidence never exceeds 'moderate' for a modelled figure: no venue "
            "quote was observed for this size"
        )

    if estimate and not estimate.within_model:
        warnings.append(
            "this exit is " + str(round(estimate.pool_fraction * 100, 1))
            + "% of the pool, past the " + str(round(model.MODEL_VALIDITY_LIMIT * 100))
            + "% point where a constant-product curve stops describing a real "
            "venue; treat the modelled figure as a floor on the true cost"
        )

    if volume and liquidity and volume < liquidity * 0.02:
        warnings.append(
            "24h volume is under 2% of pool liquidity; the pool may be deep but "
            "inactive, and a patient exit could take far longer than modelled"
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
        basis=basis,
        quote=quote,
        depth=depth,
        model_check=model_check,
        venue_failures=venue.failures,
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
    "What it costs to exit a position at a given size, and the largest size "
    "that clears a slippage ceiling. Uses an executable venue quote when one "
    "exists (basis: quoted) and a constant-product model otherwise (basis: "
    "modelled), shows the gap between the two, and returns null rather than "
    "zero when an input is unavailable. Returns RYO's public response envelope."
)


def describe() -> dict[str, Any]:
    """The MCP tool definition, ready to register on a server."""
    return {
        "name": SKILL_NAME,
        "description": DESCRIPTION,
        "inputSchema": INPUT_SCHEMA,
    }


def call(arguments: dict[str, Any], facts: MarketFacts, **kwargs: Any) -> dict[str, Any]:
    """Tool-call entry point: schema arguments in, the report's data out."""
    return assess(
        arguments["token"],
        facts,
        size_usd=arguments.get("size_usd"),
        max_slippage=arguments.get("max_slippage_pct", DEFAULT_MAX_SLIPPAGE * 100) / 100,
        participation=arguments.get("participation_pct", DEFAULT_PARTICIPATION * 100) / 100,
        **kwargs,
    ).to_dict()


def call_envelope(
    arguments: dict[str, Any],
    facts: MarketFacts,
    *,
    data_mode: str,
    extra_warnings: tuple[str, ...] = (),
    **kwargs: Any,
) -> dict[str, Any]:
    """Tool-call entry point in RYO's public response envelope.

    `request` echoes the normalised arguments, as RYO's own tools do.
    """
    request = {
        "token": str(arguments["token"]).upper(),
        "size_usd": arguments.get("size_usd"),
        "max_slippage_pct": arguments.get("max_slippage_pct", DEFAULT_MAX_SLIPPAGE * 100),
        "participation_pct": arguments.get("participation_pct", DEFAULT_PARTICIPATION * 100),
    }
    report = assess(
        request["token"],
        facts,
        size_usd=request["size_usd"],
        max_slippage=request["max_slippage_pct"] / 100,
        participation=request["participation_pct"] / 100,
        **kwargs,
    )
    return report.to_envelope(request=request, data_mode=data_mode, extra_warnings=extra_warnings)
